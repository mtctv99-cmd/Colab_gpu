    def create_voice_clone_prompt(
        self,
        ref_audio: Union[str, tuple[torch.Tensor, int]],
        ref_text: Optional[str] = None,
        preprocess_prompt: bool = True,
    ) -> VoiceClonePrompt:
        """Create a reusable voice clone prompt from reference audio.

        Args:
            ref_audio: File path (str) or ``(waveform, sample_rate)`` tuple.
                waveform should be a 1-D or 2-D torch.Tensor (channels x samples).
            ref_text: Transcript of the reference audio. If ``None``, the
                ASR model will be used to auto-transcribe (must call
                :meth:`load_asr_model` first).
            preprocess_prompt: If ``True`` (default), apply silence removal and
                trimming to the reference audio, add punctuation in the end
                of reference text (if not already)

        Returns:
            A :class:`VoiceClonePrompt` that can be passed to :meth:`generate`.
        """
        if self.audio_tokenizer is None:
            raise RuntimeError(
                "Audio tokenizer is not loaded. Make sure you loaded the model "
                "with OmniVoice.from_pretrained()."
            )

        if isinstance(ref_audio, str):
            ref_wav = load_audio(ref_audio, self.sampling_rate)
        else:
            waveform, sr = ref_audio
            if isinstance(waveform, torch.Tensor):
                waveform = waveform.cpu().numpy()
            if waveform.ndim == 1:
                waveform = waveform[np.newaxis, :]
            if waveform.shape[0] > 1:
                waveform = np.mean(waveform, axis=0, keepdims=True)
            if sr != self.sampling_rate:
                waveform = torchaudio.functional.resample(
                    torch.from_numpy(waveform),
                    orig_freq=sr,
                    new_freq=self.sampling_rate,
                ).numpy()
            ref_wav = waveform

        ref_rms = float(np.sqrt(np.mean(ref_wav**2)))
        if 0 < ref_rms < 0.1:
            ref_wav = ref_wav * 0.1 / ref_rms

        if preprocess_prompt:
            # Trim long reference audio (>20s) by splitting at the largest silence gap.
            # Skip trimming when ref_text is user-provided, otherwise the
            # trimmed audio will no longer match the full transcript.
            if ref_text is None:
                ref_wav = trim_long_audio(
                    ref_wav, self.sampling_rate, trim_threshold=20.0
                )
            ref_wav = remove_silence(
                ref_wav,
                self.sampling_rate,
                mid_sil=200,
                lead_sil=100,
                trail_sil=200,
            )
            if ref_wav.shape[-1] == 0:
                raise ValueError(
                    "Reference audio is empty after silence removal. "
                    "Try setting preprocess_prompt=False."
                )

        ref_duration = ref_wav.shape[-1] / self.sampling_rate
        if ref_duration > 20.0:
            logger.warning(
                "Reference audio is %.1fs long (>20s). This may cause slower "
                "generation, higher memory usage, and degraded voice cloning "
                "quality. We recommend trimming it to 3-10s.",
                ref_duration,
            )

        # Auto-transcribe if ref_text not provided
        if ref_text is None:
            if self._asr_pipe is None:
                logger.info("ASR model not loaded yet, loading on-the-fly ...")
                self.load_asr_model()
            ref_text = self.transcribe((ref_wav, self.sampling_rate))
            logger.debug("Auto-transcribed ref_text: %s", ref_text)

        chunk_size = self.audio_tokenizer.config.hop_length
        clip_size = int(ref_wav.shape[-1] % chunk_size)
        ref_wav = ref_wav[:, :-clip_size] if clip_size > 0 else ref_wav
        # numpy → torch at tokenizer boundary
        ref_wav_tensor = torch.from_numpy(ref_wav).to(self.audio_tokenizer.device)
        ref_audio_tokens = self.audio_tokenizer.encode(
            ref_wav_tensor.unsqueeze(0),
        ).audio_codes.squeeze(
            0
        )  # (C, T)

        if preprocess_prompt:
            ref_text = add_punctuation(ref_text)

        return VoiceClonePrompt(
            ref_audio_tokens=ref_audio_tokens,
            ref_text=ref_text,
            ref_rms=ref_rms,
        )

