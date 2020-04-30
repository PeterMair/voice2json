"""Word pronunciation methods for voice2json."""
import argparse
import asyncio
import io
import logging
import shlex
import sys
import time
import typing
from xml.etree import ElementTree as etree

import pydash

from .core import Voice2JsonCore

_LOGGER = logging.getLogger("voice2json.pronounce")

# -----------------------------------------------------------------------------


async def pronounce(args: argparse.Namespace, core: Voice2JsonCore) -> None:
    """Pronounce one or more words from a dictionary or by guessing."""
    import rhasspynlu

    # Load settings
    phoneme_pronunciations = bool(
        pydash.get(core.profile, "speech-to-text.phoneme-pronunciations", True)
    )

    play_command = shlex.split(pydash.get(core.profile, "audio.play-command"))
    word_casing = pydash.get(core.profile, "training.word-casing", "ignore").lower()
    g2p_exists = False

    pronunciations: rhasspynlu.g2p.PronunciationsType = {}

    if phoneme_pronunciations:
        # Make sure profile has been trained
        assert core.check_trained(), "Not trained"

        base_dictionary_path = core.ppath(
            "training.base_dictionary", "base_dictionary.txt"
        )
        dictionary_path = core.ppath("training.dictionary", "dictionary.txt")
        custom_words_path = core.ppath("training.custom-words-file", "custom_words.txt")
        g2p_path = core.ppath("training.g2p-model", "g2p.fst")
        g2p_exists = bool(g2p_path and g2p_path.exists())

        # Load dictionaries
        dictionary_paths = [dictionary_path, base_dictionary_path]

        if custom_words_path and custom_words_path.exists():
            dictionary_paths.insert(0, custom_words_path)

        for dict_path in dictionary_paths:
            if dict_path and dict_path.exists():
                _LOGGER.debug("Loading pronunciation dictionary from %s", dict_path)
                with open(dict_path, "r") as dict_file:
                    pronunciations = rhasspynlu.g2p.read_pronunciations(
                        dict_file, pronunciations
                    )

    # True if audio will go to stdout.
    # In this case, printing will go to stderr.
    wav_stdout = args.wav_sink == "-"

    print_file = sys.stderr if wav_stdout else sys.stdout

    # Load text to speech system
    marytts_voice = pydash.get(core.profile, "text-to-speech.marytts.voice")

    if not args.quiet:
        if args.espeak or (marytts_voice is None):
            # Use eSpeak
            do_pronounce = get_pronounce_espeak(args, core)
        else:
            # Use MaryTTS
            do_pronounce = get_pronounce_marytts(args, core, marytts_voice)
    else:
        # Quiet
        async def do_pronounce(word: str, dict_phonemes: typing.Iterable[str]) -> bytes:
            return bytes()

    # -------------------------------------------------------------------------

    if args.word:
        words = args.word
    else:
        words = sys.stdin

    # Process words
    try:
        for word in words:
            word_parts = word.strip().split()
            word = word_parts[0]
            dict_phonemes = []

            if word_casing == "upper":
                word = word.upper()
            elif word_casing == "lower":
                word = word.lower()

            if len(word_parts) > 1:
                # Pronunciation provided
                dict_phonemes.append(word_parts[1:])

            if not phoneme_pronunciations:
                # Use word itself if acoustic model does not use phonemes
                dict_phonemes.append(word)
            elif word in pronunciations:
                # Use pronunciations from dictionary
                dict_phonemes.extend(phonemes for phonemes in pronunciations[word])
            elif g2p_exists:
                # Don't guess if a pronunciation was provided
                if not dict_phonemes:
                    # Guess pronunciation with phonetisaurus
                    _LOGGER.debug("Guessing pronunciation for %s", word)
                    assert g2p_path, "No g2p path"

                    guesses = rhasspynlu.g2p.guess_pronunciations(
                        [word], g2p_path, num_guesses=args.nbest
                    )
                    for _, phonemes in guesses:
                        dict_phonemes.append(phonemes)
            else:
                _LOGGER.warning("No pronunciation for %s", word)

            # Avoid duplicate pronunciations
            used_pronunciations: typing.Set[str] = set()

            for phonemes in dict_phonemes:
                phoneme_str = " ".join(phonemes)
                if phoneme_str in used_pronunciations:
                    continue

                print(word, phoneme_str, file=print_file)
                print_file.flush()

                used_pronunciations.add(phoneme_str)

                if not args.quiet:
                    # Speak with espeak or MaryTTS
                    wav_data = await do_pronounce(word, phonemes)

                    if args.wav_sink is not None:
                        # Write WAV output somewhere
                        if args.wav_sink == "-":
                            # STDOUT
                            wav_sink = sys.stdout.buffer
                        else:
                            # File output
                            wav_sink = open(args.wav_sink, "wb")

                        wav_sink.write(wav_data)
                        wav_sink.flush()
                    else:
                        # Play audio directly
                        _LOGGER.debug(play_command)
                        play_process = await asyncio.create_subprocess_exec(
                            play_command[0],
                            *play_command[1:],
                            stdin=asyncio.subprocess.PIPE,
                        )
                        await play_process.communicate(input=wav_data)

                    # Delay before next word
                    time.sleep(args.delay)

            if args.newline:
                print("", file=print_file)
                print_file.flush()

    except KeyboardInterrupt:
        pass


# -----------------------------------------------------------------------------


def get_pronounce_espeak(
    args: argparse.Namespace, core: Voice2JsonCore
) -> typing.Callable[
    [str, typing.Iterable[str]], typing.Coroutine[typing.Any, typing.Any, bytes]
]:
    """Get pronounce method for eSpeak."""
    # Use eSpeak
    espeak_voice = pydash.get(core.profile, "text-to-speech.espeak.voice")
    espeak_map_path = core.ppath(
        "text-to-speech.espeak.phoneme-map", "espeak_phonemes.txt"
    )

    assert (
        espeak_map_path and espeak_map_path.exists()
    ), f"Missing eSpeak phoneme map at {espeak_map_path}"

    espeak_phoneme_map: typing.Dict[str, str] = {}

    with open(espeak_map_path, "r") as map_file:
        for line in map_file:
            line = line.strip()
            if line:
                parts = line.split(maxsplit=1)
                espeak_phoneme_map[parts[0]] = parts[1]

    espeak_cmd_format = pydash.get(
        core.profile, "text-to-speech.espeak.pronounce-command"
    )

    async def do_pronounce(word: str, dict_phonemes: typing.Iterable[str]) -> bytes:
        espeak_phonemes = [espeak_phoneme_map[p] for p in dict_phonemes]
        espeak_str = "".join(espeak_phonemes)
        espeak_cmd = shlex.split(espeak_cmd_format.format(phonemes=espeak_str))

        if espeak_voice is not None:
            espeak_cmd.extend(["-v", str(espeak_voice)])

        _LOGGER.debug(espeak_cmd)
        process = await asyncio.create_subprocess_exec(
            *espeak_cmd, stdout=asyncio.subprocess.PIPE
        )
        stdout, _ = await process.communicate()
        return stdout

    return do_pronounce


# -----------------------------------------------------------------------------


def get_pronounce_marytts(
    args: argparse.Namespace, core: Voice2JsonCore, marytts_voice: str
) -> typing.Callable[
    [str, typing.Iterable[str]], typing.Coroutine[typing.Any, typing.Any, bytes]
]:
    """Get pronounce method for MaryTTS."""
    marytts_map_path = core.ppath(
        "text-to-speech.marytts.phoneme-map", "marytts_phonemes.txt"
    )

    assert (
        marytts_map_path and marytts_map_path.exists()
    ), "Missing MaryTTS phoneme map at {marytts_map_path}"

    marytts_phoneme_map: typing.Dict[str, str] = {}

    with open(marytts_map_path, "r") as map_file:
        for line in map_file:
            line = line.strip()
            if line:
                parts = line.split(maxsplit=1)
                marytts_phoneme_map[parts[0]] = parts[1]

    marytts_locale = pydash.get(
        core.profile,
        "text-to-speech.marytts.locale",
        pydash.get(core.profile, "language.code"),
    )
    marytts_url = str(
        pydash.get(
            core.profile,
            "text-to-speech.marytts.process-url",
            "http://localhost:59125/process",
        )
    )

    # Set up default params
    marytts_params: typing.Dict[str, str] = {
        "AUDIO": "WAVE",
        "OUTPUT_TYPE": "AUDIO",
        "VOICE": marytts_voice,
    }

    if marytts_locale:
        marytts_params["LOCALE"] = marytts_locale

    # End of sentence token
    sentence_end = pydash.get(core.profile, "text-to-speech.marytts.sentence-end", "")

    # Rate of pronunciation
    pronounce_rate = str(
        pydash.get(core.profile, "text-to-speech.marytts.pronounce-rate", "5%")
    )

    async def do_pronounce(word: str, dict_phonemes: typing.Iterable[str]) -> bytes:
        marytts_phonemes = [marytts_phoneme_map[p] for p in dict_phonemes]
        phoneme_str = " ".join(marytts_phonemes)
        _LOGGER.debug(phoneme_str)

        # Construct MaryXML input
        mary_xml = etree.fromstring(
            """<?xml version="1.0" encoding="UTF-8"?>
        <maryxml version="0.5" xml:lang="en-US">
        <p><prosody rate="100%"><s><phrase></phrase></s></prosody></p>
        </maryxml>"""
        )

        s = next(mary_xml.iter())
        p = next(s.iter())
        p.attrib["rate"] = pronounce_rate

        phrase = next(iter(p.iter()))
        t = etree.SubElement(phrase, "t", attrib={"ph": phoneme_str})
        t.text = word

        if len(sentence_end) > 0:
            # Add end of sentence token
            eos = etree.SubElement(phrase, "t", attrib={"pos": "."})
            eos.text = sentence_end

        # Serialize XML
        with io.BytesIO() as xml_file:
            etree.ElementTree(mary_xml).write(
                xml_file, encoding="utf-8", xml_declaration=True
            )

            xml_string = xml_file.getvalue().decode()
            request_params = {
                "INPUT_TYPE": "RAWMARYXML",
                "INPUT_TEXT": xml_string,
                **marytts_params,
            }

        _LOGGER.debug("%s %s", marytts_url, request_params)

        async with core.http_session.get(
            marytts_url, params=request_params, ssl=core.ssl_context
        ) as response:
            data = await response.read()
            if response.status != 200:
                # Print error message
                _LOGGER.error(data.decode())

            response.raise_for_status()
            return data

    return do_pronounce
