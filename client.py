import asyncio
import websockets
import json
import time
import uuid
import wave
import argparse
from config import REQ_TIMEOUT_S, REQ_CHUNK_SIZE_MS, REQ_CHUNK_SIZE_FRAME, SERVER_URI, EOS_STR, EOS_BYTE
from random import shuffle
import struct
import random

latency_logs = []
all_latency = []

async def send_audio(websocket, audio_file):
    with wave.open(audio_file, 'rb') as file:
        sample_width = file.getsampwidth()
        while True:
            audio_chunk = file.readframes(REQ_CHUNK_SIZE_FRAME)
            latency_logs.append(time.time())
            if len(audio_chunk) > 0:
                await websocket.send(audio_chunk)
                await asyncio.sleep(REQ_CHUNK_SIZE_MS / 1000)
            else:
                print('Sending EOS')
                await websocket.send(EOS_BYTE)
                break

async def listen_results(websocket):
    try:
        transcription = None
        while transcription != EOS_STR:
            prev = time.time()
            transcription = await asyncio.wait_for(websocket.recv(), REQ_TIMEOUT_S)
            lat = time.time() - latency_logs.pop(0)
            all_latency.append(lat)
            print("ASR Result:", transcription, " | Latency: ", lat)
    except websockets.exceptions.ConnectionClosed:
        print("Connection closed")
    except Exception as e:
        print(f"Error receiving transcription: {e}")

async def process_file(audio_file):
    try:
        async with websockets.connect(SERVER_URI) as websocket:
            send_task = asyncio.create_task(send_audio(websocket, audio_file))
            listen_task = asyncio.create_task(listen_results(websocket))
            await send_task
            await listen_task
    except Exception as e:
        print(f"Error processing file {audio_file}: {e}")

async def main(num_repeat):
    AUDIO_FILES = ['audios/' + str(i) + '.wav' for i in range(10)] * num_repeat
    shuffle(AUDIO_FILES)
    
    global latency_logs
    for audio_file in AUDIO_FILES:
        print(f"Processing {audio_file}")
        await process_file(audio_file)
        await asyncio.sleep(2)
        latency_logs = []
        print("Avg latency:", sum(all_latency)/len(all_latency))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--num_repeat', type=int, default=10, help='Number of times to repeat the audio files')
    args = parser.parse_args()
    asyncio.run(main(args.num_repeat))
