# Source code adapted from https://github.com/NVIDIA/NeMo/blob/main/tutorials/asr/Online_ASR_Microphone_Demo_Cache_Aware_Streaming.ipynb
import torch
import copy
import time
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from nemo.collections.asr.models.ctc_bpe_models import EncDecCTCModelBPE
from nemo.collections.asr.parts.utils.rnnt_utils import Hypothesis
from nemo.utils import logging
from omegaconf import OmegaConf, open_dict
import nemo.collections.asr as nemo_asr
from torch.cuda.amp import autocast

logging.setLevel(logging.ERROR)

class ASR:
    def __init__(self, model_name = "./stt_en_fastconformer_hybrid_large_streaming_multi.nemo",
                 chunk_size_ms = 200,
                 lookahead_ms = 80, # [0, 80, 480, 1040]
                 decoder_type = 'rnnt',
                 bs = 32,
                 use_fp16=True):
        
        # Load the ASR model
        asr_model = nemo_asr.models.ASRModel.restore_from(restore_path=model_name)
        asr_model.eval()
        
        step_ms = 80
        self.chunk_size_frame = int((chunk_size_ms / 1000) * asr_model.cfg.sample_rate)
        
        if "stt_en_fastconformer_hybrid_large_streaming_multi" in model_name:
            left_context_size = asr_model.encoder.att_context_size[0]
            asr_model.encoder.set_default_att_context_size([left_context_size, int(lookahead_ms / step_ms)])
        
        # Set decoding strategy
        asr_model.change_decoding_strategy(decoder_type=decoder_type)
        decoding_cfg = asr_model.cfg.decoding
        with open_dict(decoding_cfg):
            decoding_cfg.strategy = "greedy"
            decoding_cfg.preserve_alignments = False
            if hasattr(asr_model, 'joint'):
                decoding_cfg.greedy.max_symbols = 10
                decoding_cfg.fused_batch_size = bs
            asr_model.change_decoding_strategy(decoding_cfg)
        
        # Audio preprocessor
        cfg = copy.deepcopy(asr_model._cfg)
        OmegaConf.set_struct(cfg.preprocessor, False)        
        cfg.preprocessor.dither = 0.0
        cfg.preprocessor.pad_to = 0
        cfg.preprocessor.normalize = "None"
        preprocessor = EncDecCTCModelBPE.from_config_dict(cfg.preprocessor)
        preprocessor.to(asr_model.device)
        
        # Dummy cache
        pre_encode_cache_size = asr_model.encoder.streaming_cfg.pre_encode_cache_size[1]
        num_channels = asr_model.cfg.preprocessor.features
        self.cache_last_channel, self.cache_last_time, self.cache_last_channel_len = asr_model.encoder.get_initial_cache_state(batch_size=bs)
        self.cache_pre_encode = torch.zeros((bs, num_channels, pre_encode_cache_size), device=asr_model.device)
        self.previous_hypotheses, self.pred_out_stream = [None] * bs, [None] * bs
        
        # Cached states of previous predictions
        self.cached_states = {}
        
        # Store model and preprocessor
        self.model = asr_model
        self.preprocessor = preprocessor
        self.pre_encode_cache_size = pre_encode_cache_size

        # Option to use FP16
        self.use_fp16 = use_fp16
        if self.use_fp16:
            self.model = self.model.half()
            self.cache_last_channel = self.cache_last_channel.half()
            self.cache_last_time = self.cache_last_time.half()
            self.cache_last_channel_len = self.cache_last_channel_len.half()
            self.cache_pre_encode = self.cache_pre_encode.half()

        print('Model inited!')
    
    def clear_cache(self, sessions):
        for idx in sessions:
            if idx in self.cached_states:
                del self.cached_states[idx]

    def set_batch_size_decoding(self, bs):
        decoding_cfg = self.model.cfg.decoding
        with open_dict(decoding_cfg):
            decoding_cfg.fused_batch_size = bs
            self.model.change_decoding_strategy(decoding_cfg)

    def preprocess_audio(self, audio):
        audio = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
        padding_length = max(0, self.chunk_size_frame - len(audio))
        audio = np.pad(audio, (0, padding_length), mode='constant', constant_values=0)[:self.chunk_size_frame]
        audio_signal = torch.from_numpy(audio).unsqueeze_(0).to(self.model.device)
        audio_signal_len = torch.Tensor([audio.shape[0]]).to(self.model.device)
        
        processed_signal, processed_signal_length = self.preprocessor(
            input_signal=audio_signal, length=audio_signal_len
        )
        return processed_signal, processed_signal_length

    def get_dummy_cache(self, bs):
        return (self.cache_last_channel[:,:bs,:,:].clone(),
                self.cache_last_time[:,:bs,:,:].clone(),
                self.cache_last_channel_len[:bs].clone(),
                self.cache_pre_encode[:bs].clone(),
                self.previous_hypotheses[:bs].copy(),
                self.pred_out_stream[:bs].copy()
               )

    def predict(self, messages):
        self.set_batch_size_decoding(len(messages))
        (
            cache_last_channel,
            cache_last_time,
            cache_last_channel_len,
            cache_pre_encode,
            previous_hypotheses,
            pred_out_stream
        ) = self.get_dummy_cache(len(messages))

        # Replace dummy cache with real cache 
        for i in range(0, len(messages)):
            sid = messages[i]['session_id']
            if sid in self.cached_states:
                cache_last_channel[:,i,:,:] = self.cached_states[sid]['cache_last_channel']
                cache_last_time[:,i,:,:] = self.cached_states[sid]['cache_last_time']
                cache_last_channel_len[i] = self.cached_states[sid]['cache_last_channel_len']
                cache_pre_encode[i] = self.cached_states[sid]['cache_pre_encode']
                previous_hypotheses[i] = self.cached_states[sid]['previous_hypotheses']
                pred_out_stream[i] = self.cached_states[sid]['pred_out_stream']

        ## --- TO DO  padding so that the chunk_data for each message is equal ---- ###
        
        chunk_data = [mess['data'] for mess in messages]
        with ThreadPoolExecutor(min(len(messages), 4)) as executor:
            results = list(executor.map(self.preprocess_audio, chunk_data))
        processed_signal, processed_signal_length = map(list, zip(*results))

        processed_signal = torch.cat(processed_signal, dim = 0)
        processed_signal_length = torch.cat(processed_signal_length, dim = 0)
        processed_signal = torch.cat([cache_pre_encode, processed_signal], dim=-1)
        processed_signal_length += cache_pre_encode.shape[1]
        
        if self.use_fp16:
            processed_signal = processed_signal.half()
            processed_signal_length = processed_signal_length.half()
        
        cache_pre_encode = processed_signal[:, :, -self.pre_encode_cache_size:]
        
        with torch.no_grad():
            (
                pred_out_stream,
                transcribed_texts,
                cache_last_channel,
                cache_last_time,
                cache_last_channel_len,
                previous_hypotheses,
            ) = self.model.conformer_stream_step(
                processed_signal=processed_signal,
                processed_signal_length=processed_signal_length,
                cache_last_channel=cache_last_channel,
                cache_last_time=cache_last_time,
                cache_last_channel_len=cache_last_channel_len,
                keep_all_outputs=False,
                previous_hypotheses=previous_hypotheses,
                previous_pred_out=pred_out_stream,
                drop_extra_pre_encoded=None,
                return_transcription=True,
            )
        
        for i in range(0, len(messages)):
            self.cached_states[messages[i]['session_id']] = {'cache_last_channel' : cache_last_channel[:,i,:,:],
                                                             'cache_last_time' : cache_last_time[:,i,:,:],
                                                             'cache_last_channel_len' : cache_last_channel_len[i],
                                                             'cache_pre_encode' : cache_pre_encode[i],
                                                             'previous_hypotheses' : previous_hypotheses[i],
                                                             'pred_out_stream' :  pred_out_stream[i]
                                                            }

        transcriptions = [hyp.text if isinstance(hyp, Hypothesis) else '' for hyp in transcribed_texts]
        return transcriptions
