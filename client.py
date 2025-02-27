import asyncio
import websockets
import json
import time
import uuid
import wave
from config import REQ_TIMEOUT_S, REQ_CHUNK_SIZE_BYTE, SERVER_URI, EOS_STR, EOS_BYTE, REQ_MIN_CHUNK_SIZE_BYTE
from random import shuffle

AUDIO_FILES = ['audios/' + str(i) + '.wav' for i in range(0,10)] * 100
shuffle(AUDIO_FILES)

async def send_audio(websocket, audio_file):
    with wave.open(audio_file, 'rb') as file:        
        while True:
            audio_chunk = file.readframes(REQ_CHUNK_SIZE_BYTE)
            if len(audio_chunk) == REQ_MIN_CHUNK_SIZE_BYTE:
                await websocket.send(audio_chunk)
                await asyncio.sleep(0.1)
            else:
                print('Sending EOS')
                await websocket.send(EOS_BYTE)
                break

async def listen_results(websocket):
    try:
        transcription = None
        while transcription != EOS_STR:
            transcription = await asyncio.wait_for(websocket.recv(), REQ_TIMEOUT_S)
            print(f"ASR Result: {transcription}")
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

async def main():
    for audio_file in AUDIO_FILES:
        print(f"Processing {audio_file}")
        await process_file(audio_file)
        await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())