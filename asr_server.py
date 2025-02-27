from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import asyncio
import random
import json
from collections import deque, defaultdict
import time
from asr import ASR
from config import BATCHING_SIZE, BATCHING_TIMEOUT_MS, EOS_STR, EOS_BYTE, ASR_MODEL

#--------------------------------------#
app = FastAPI()
active_clients = {}
expired_sessions = set()
message_queue = defaultdict(deque)
model = ASR(model_name = ASR_MODEL, bs = BATCHING_SIZE)
#--------------------------------------#

async def inference(batch):
    to_be_inferred = [req for req in batch if req['data'] != EOS_BYTE]
    transcriptions = model.predict(to_be_inferred) if to_be_inferred else []    
    results = []
    transcription_index = 0
    for req in batch:
        if req['data'] == EOS_BYTE:
            results.append(EOS_STR)
        else:
            results.append(transcriptions[transcription_index])
            transcription_index += 1
    return results

def clean_up_session():
    sessions_to_remove = set()
    for session_id in expired_sessions:
        if not message_queue[session_id]:
            sessions_to_remove.add(session_id)
            if session_id in active_clients:
                del active_clients[session_id]
            if session_id in message_queue:
                del message_queue[session_id]
            model.clear_cache([session_id])
    expired_sessions.difference_update(sessions_to_remove)

async def process_message_queue():
    batch = []
    batch_start_time = time.time()
    
    while True:
        q_view, q_len = message_queue.items(), len(message_queue.items())
        for idx, (session_id, session_q) in enumerate(q_view):
        
            if session_q:
                batch.append(session_q.popleft())
            
            if len(batch) > BATCHING_SIZE or time.time() - batch_start_time > BATCHING_TIMEOUT_MS or idx == q_len - 1:
                if batch:
                    transcriptions = await inference(batch)
                    for i, transcription in enumerate(transcriptions):
                        session_id = batch[i]['session_id']
                        if session_id in active_clients:
                            await active_clients[session_id].send_text(transcription)
                
                batch = []
                batch_start_time = time.time()
        
        clean_up_session()
        await asyncio.sleep(0.02)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    session_id = str(id(websocket))
    active_clients[session_id] = websocket
    print(f"Client connected with session ID: {session_id}")
    try:
        async for chunk_data in websocket.iter_bytes():
            message_queue[session_id].append({'session_id': session_id, 'data': chunk_data})
    except WebSocketDisconnect:
        print(f"Client disconnected: {session_id}")
    finally:
        expired_sessions.add(session_id)
        print(len(message_queue), len(active_clients), len(model.cached_states), len(expired_sessions))

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(process_message_queue())
    print('waiting for client!')

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.get("/")
async def root():
    return {"message": "Welcome to the ASR service!"}