#!/usr/bin/env python
import audioop
from googleapiclient.discovery import build
import json
import math
import psutil
from multiprocessing import Pool, Manager
import os
import requests
import subprocess
import tempfile
import wave
import re
from random import choice
from progressbar import ProgressBar, Percentage, Bar, ETA
from autosub.constants import LANGUAGE_CODES, AUDIO_CODECS, GOOGLE_SPEECH_API_KEY, GOOGLE_SPEECH_API_URL
from autosub.formatters import FORMATTERS
from autosub.tor_ip_changer import IPChanger

import autosub.autosub_wrapper


def percentile(arr, percent):
    arr = sorted(arr)
    k = (len(arr) - 1) * percent
    f = math.floor(k)
    c = math.ceil(k)
    if f == c: return arr[int(k)]
    d0 = arr[int(f)] * (c - k)
    d1 = arr[int(c)] * (k - f)
    return d0 + d1


def is_same_language(lang1, lang2):
    return lang1.split("-")[0] == lang2.split("-")[0]


def remove_flac_files():
    import glob
    for fname in glob.glob(os.path.join(tempfile.gettempdir(), '*.flac')):
        os.remove(fname)

        
class FLACConverter(object):
    def __init__(self, source_path, include_before=0.25, include_after=0.25):
        self.source_path = source_path
        self.include_before = include_before
        self.include_after = include_after

    def __call__(self, region):
        try:
            start, end = region
            start = max(0, start - self.include_before)
            end += self.include_after
            temp = tempfile.NamedTemporaryFile(suffix='.flac', delete=False)
            command = ["ffmpeg", "-ss", str(start), "-t", str(end - start),
                       "-y", "-i", self.source_path,
                       "-loglevel", "error", temp.name]
            use_shell = True if os.name == "nt" else False
            subprocess.check_output(command, stdin=open(os.devnull), shell=use_shell)
            temp_data = temp.read()
            temp.close()
            return temp_data

        except KeyboardInterrupt:
            return


class SpeechRecognizer(object):
    def __init__(self, language="en", rate=44100, retries=3, use_tor=False):
        self.language = language
        self.rate = rate
        self.retries = retries
        self.use_tor = use_tor

    @staticmethod
    def build_tor_object():
        tor_object = None
        if os.getpid() not in autosub.autosub_wrapper.shared_tor_control:
            tor_ports = autosub.autosub_wrapper.shared_ports.pop()
            print('NOOT INNNN', tor_ports)
            if tor_ports:
                autosub.autosub_wrapper.shared_tor_control[os.getpid()] = tor_ports
                tor_object = IPChanger(socks_port=tor_ports[0], control_port=tor_ports[1])
                tor_object.do()
        else:
            tor_ports = autosub.autosub_wrapper.shared_tor_control[os.getpid()]
            tor_object = IPChanger(socks_port=tor_ports[0], control_port=tor_ports[1])
        return tor_object

    def __call__(self, data):
        try:
            tor_obj = None
            if self.use_tor:
                tor_obj = self.build_tor_object()

            speech_key = data[0]
            speech_data = data[1]
            for i in range(self.retries):
                url = GOOGLE_SPEECH_API_URL.format(lang=self.language, key=speech_key)
                headers = {"Content-Type": "audio/x-flac; rate=%d" % self.rate}

                try:
                    resp = requests.post(url, data=speech_data, headers=headers)
                except requests.exceptions.ConnectionError:
                    if tor_obj:
                        tor_obj.do()
                    continue

                if resp.status_code is not 200:
                    if tor_obj:
                        tor_obj.do()
                    continue

                response_data = resp.content
                try:
                    if type(response_data) is not str:
                        response_data = response_data.decode()
                except AttributeError:
                    return

                for line in response_data.split("\n"):
                    try:
                        line = json.loads(line)
                        line = line['result'][0]['alternative'][0]['transcript']
                        return line[:1].upper() + line[1:]
                    except:
                        # no result
                        continue

        except KeyboardInterrupt:
            return


class Translator(object):
    def __init__(self, language, api_key, src, dst):
        self.language = language
        self.api_key = api_key
        self.service = build('translate', 'v2',
                             developerKey=self.api_key)
        self.src = src
        self.dst = dst

    def __call__(self, sentence):
        try:
            if not sentence:
                return
            result = self.service.translations().list(
                source=self.src,
                target=self.dst,
                q=[sentence]
            ).execute()
            if 'translations' in result and len(result['translations']) and \
                            'translatedText' in result['translations'][0]:
                return result['translations'][0]['translatedText']
            return ""

        except KeyboardInterrupt:
            return


def which(program):
    def is_exe(fpath):
        return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

    fpath, fname = os.path.split(program)
    if fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ["PATH"].split(os.pathsep):
            path = path.strip('"')
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file
    return None


def get_audio_codecs(filename):
    command = ['ffmpeg', '-i', filename]
    output = subprocess.getoutput(command)
    if output:
        m = re.search(r'Stream.+Audio:([^\n]+)', output, re.MULTILINE)
        if m:
            audio_codec = m.group(1).lower()
            for codec in AUDIO_CODECS:
                if codec in audio_codec:
                    return codec
    return None


def extract_audio(filename, channels=1, rate=16000):
    temp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
    if not os.path.isfile(filename):
        print("The given file does not exist: {0}".format(filename))
        raise Exception("Invalid filepath: {0}".format(filename))
    if not which("ffmpeg.exe"):
        print("ffmpeg: Executable not found on machine.")
        raise Exception("Dependency not found: ffmpeg")

    audio_codec = get_audio_codecs(filename)
    if not audio_codec:
        raise Exception("Unknown audio codec")

    command = ["ffmpeg", "-c:v", "rawvideo", "-c:a", audio_codec, "-y", "-i", filename, "-ac", str(channels), "-ar",
               str(rate), "-loglevel", "error", temp.name]
    use_shell = True if os.name == "nt" else False
    subprocess.check_output(command, stdin=open(os.devnull), shell=use_shell)
    return temp.name, rate


def find_speech_regions(filename, frame_width=4096, min_region_size=0.5, max_region_size=6):
    reader = wave.open(filename)
    sample_width = reader.getsampwidth()
    rate = reader.getframerate()
    n_channels = reader.getnchannels()
    chunk_duration = float(frame_width) / rate

    n_chunks = int(math.ceil(reader.getnframes() * 1.0 / frame_width))
    energies = []

    for i in range(n_chunks):
        chunk = reader.readframes(frame_width)
        energies.append(audioop.rms(chunk, sample_width * n_channels))

    threshold = percentile(energies, 0.2)

    elapsed_time = 0

    regions = []
    region_start = None

    for energy in energies:
        is_silence = energy <= threshold
        max_exceeded = region_start and elapsed_time - region_start >= max_region_size

        if (max_exceeded or is_silence) and region_start:
            if elapsed_time - region_start >= min_region_size:
                regions.append((region_start, elapsed_time))
                region_start = None

        elif (not region_start) and (not is_silence):
            region_start = elapsed_time
        elapsed_time += chunk_duration
    return regions


def pad_keys(key_list, size):
    lenk = len(key_list)
    if size <= lenk:
        return key_list[:size]
    else:
        d, m = divmod(size, lenk)
        if d > 1:
            key_list.extend(key_list * (d - 1))
            key_list += key_list[:m]
    return key_list


def init_pool_process(shared_dict, shared_list):
    p = psutil.Process(os.getpid())
    p.nice(psutil.REALTIME_PRIORITY_CLASS)
    autosub.autosub_wrapper.shared_tor_control = shared_dict
    autosub.autosub_wrapper.shared_ports = shared_list


def init_tors(instance_count, retires=3):
    ports_list = []
    for i in range(instance_count):
        for j in range(retires):
            socks_port = choice(range(9000, 15000))
            control_port = socks_port + 1
            if IPChanger(socks_port, control_port).call_tor(socks_port, control_port):
                ports_list.append((socks_port, control_port))
                break
    return ports_list


def deinit_tors():
    for proc in psutil.process_iter():
        if proc.name() == 'tor.exe':
            proc.kill()


class AutosubWrapper:
    def __init__(self, concurrency=10, min_speech_size=30, max_speech_size=60,
                 google_speech_api_key=GOOGLE_SPEECH_API_KEY, use_tor=False):
        self._concurrency = concurrency
        shared_tor_control = None
        shared_ports = None
        if use_tor:
            manager = Manager()
            shared_tor_control = manager.dict()
            shared_ports = manager.list(init_tors(self._concurrency))

        self._pool = Pool(self._concurrency, init_pool_process, initargs=(shared_tor_control, shared_ports))
        self._min_speech_size = min_speech_size
        self._max_speech_size = max_speech_size
        self._google_speech_api_key = google_speech_api_key
        if type(google_speech_api_key) == str:
            self._google_speech_api_key = [google_speech_api_key]
        self._use_tor = use_tor

    def __del__(self):
        deinit_tors()

    @staticmethod
    def print_formats():
        print("List of formats:")
        for subtitle_format in FORMATTERS.keys():
            print("{format}".format(format=subtitle_format))

    @staticmethod
    def print_languages():
        print("List of all languages:")
        for code, language in sorted(LANGUAGE_CODES.items()):
            print("{code}\t{language}".format(code=code, language=language))

    def generate(self, source_path, output, src_language, dst_language, sub_format, api_key):
        if sub_format not in FORMATTERS.keys():
            print("Subtitle format not supported. Run with --list-formats to see all supported formats.")
            return None

        if src_language not in LANGUAGE_CODES.keys():
            print("Source language not supported. Run with --list-languages to see all supported languages.")
            return None

        if dst_language not in LANGUAGE_CODES.keys():
            print("Destination language not supported. Run with --list-languages to see all supported languages.")
            return None

        if not source_path:
            print("Error: You need to specify a source path.")
            return None

        audio_filename, audio_rate = extract_audio(source_path)

        regions = find_speech_regions(audio_filename, min_region_size=self._min_speech_size,
                                      max_region_size=self._max_speech_size)

        converter = FLACConverter(source_path=audio_filename)
        recognizer = SpeechRecognizer(language=src_language, rate=audio_rate, use_tor=self._use_tor)

        transcripts = []
        if regions:
            try:
                widgets = ["Converting speech regions to FLAC files: ", Percentage(), ' ', Bar(), ' ', ETA()]
                pbar = ProgressBar(widgets=widgets, maxval=len(regions)).start()
                extracted_regions = []
                for i, extracted_region in enumerate(self._pool.imap(converter, regions)):
                    extracted_regions.append(extracted_region)
                    pbar.update(i)
                pbar.finish()

                widgets = ["Performing speech recognition: ", Percentage(), ' ', Bar(), ' ', ETA()]
                pbar = ProgressBar(widgets=widgets, maxval=len(regions)).start()

                api_keys = pad_keys(self._google_speech_api_key, len(extracted_regions))
                keys_regions = [(key, region) for key, region in zip(api_keys, extracted_regions)]
                for i, transcript in enumerate(self._pool.imap(recognizer, keys_regions)):
                    transcripts.append(transcript)
                    pbar.update(i)
                pbar.finish()

                if not is_same_language(src_language, dst_language):
                    if api_key:
                        google_translate_api_key = api_key
                        translator = Translator(dst_language, google_translate_api_key, dst=dst_language,
                                                src=src_language)
                        prompt = "Translating from {0} to {1}: ".format(src_language, dst_language)
                        widgets = [prompt, Percentage(), ' ', Bar(), ' ', ETA()]
                        pbar = ProgressBar(widgets=widgets, maxval=len(regions)).start()
                        translated_transcripts = []
                        for i, transcript in enumerate(self._pool.imap(translator, transcripts)):
                            translated_transcripts.append(transcript)
                            pbar.update(i)
                        pbar.finish()
                        transcripts = translated_transcripts
                    else:
                        print("Error: Subtitle translation requires specified Google Translate API key. \
                        See --help for further information.")
                        return 1

            except KeyboardInterrupt:
                pbar.finish()
                self._pool.terminate()
                self._pool.join()
                deinit_tors()
                print("Cancelling transcription")
                return 1

        timed_subtitles = [(r, t) for r, t in zip(regions, transcripts) if t]
        formatter = FORMATTERS.get(sub_format)
        formatted_subtitles = formatter(timed_subtitles)

        dest = output
        if not dest:
            base, ext = os.path.splitext(source_path)
            dest = "{base}.{format}".format(base=base, format=sub_format)

        with open(dest, 'wb') as f:
            f.write(formatted_subtitles.encode("utf-8"))

        print("Subtitles file created at {}".format(dest))
        os.remove(audio_filename)
        remove_flac_files()
        return source_path


if __name__ == '__main__':
    try:
        auto_sub = AutosubWrapper(concurrency=2, google_speech_api_key=['AIzaSyAFBRjVtCutgAVmVYbhnpUQCaMTOBrIxzA'],
                                  use_tor=False)
        for i in range(2):
            print(auto_sub.generate(r"D:\iptv\videos\1.Coletiva do A Valentim Estou Recuperando o Borja! - 22102017.mp4",
                                    None, 'pt', 'pt', 'json', None))
    except Exception as e:
        print(e)
        pass
