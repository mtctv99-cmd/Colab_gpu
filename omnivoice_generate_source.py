    @torch.inference_mode()
    def generate(
        self,
        text: Union[str, list[str]],
        language: Union[str, list[str], None] = None,
        ref_text: Union[str, list[str], None] = None,
        ref_audio: Union[
            str,
            list[str],
            tuple[torch.Tensor, int],
            list[tuple[torch.Tensor, int]],
            None,
        ] = None,
        voice_clone_prompt: Union[
            VoiceClonePrompt, list[VoiceClonePrompt], None
        ] = None,
        instruct: Union[str, list[str], None] = None,
        duration: Union[float, list[Optional[float]], None] = None,
        speed: Union[float, list[Optional[float]], None] = None,
        generation_config: Optional[OmniVoiceGenerationConfig] = None,
        **kwargs,
    ) -> list[np.ndarray]:
        """Generate speech audio given text in various modes.

        Supports three modes:

        1. **Voice clone** — clone the voice style from the reference audio.
            Should provide ``voice_clone_prompt`` (from
           :meth:`create_voice_clone_prompt`) or ``ref_text`` + ``ref_audio``.
        2. **Voice design** — provide ``instruct`` text describing
           the desired voice style; no reference audio needed.
        3. **Auto** — provide neither; the model picks a voice itself.

        Args:
            text: Target text (single string or list for batch).
            language: Language name (e.g. ``"English"``) or code
                (e.g. ``"en"``). ``None`` for language-agnostic mode.
                Performance is slightly better if you specify the language.
            ref_text: Optional reference text for voice cloning mode.
            ref_audio: Optional reference audio for voice cloning mode.
                Can be a file path or a (waveform, sample_rate) tuple.
            voice_clone_prompt: Reusable prompt from :meth:`create_voice_clone_prompt`.
                If provided, it overrides ``ref_text`` and ``ref_audio``.
            instruct: Style instruction for voice design mode.
            duration: Fixed output duration in seconds. If a single float,
                applies to all items; if a list, one value per item.
                ``None`` (default) lets the model estimate duration from text.
                Overrides ``speed`` when both are provided.
            speed: Speaking speed factor. ``> 1.0`` for faster, ``< 1.0`` for
                slower. If a list, one value per item. ``None`` (default) uses
                the model's default estimation.
            generation_config: Explicit config object. If provided, takes
                precedence over ``**kwargs``.
            **kwargs: Generation config or its fields:
                denoise: Whether to prepend the ``<|denoise|>`` token.
                num_step: Number of iterative decoding steps.
                guidance_scale: Classifier-free guidance scale.
                t_shift: Time-step shift (smaller → emphasise low-SNR).
                postprocess_output: Post-process output (remove silence, fade-in/out, pad edges).
                layer_penalty_factor: Penalty encouraging earlier codebook
                    layers to unmask first.
                position_temperature: Temperature for position selection.
                class_temperature: Temperature for token sampling (0 = greedy).
                audio_chunk_duration: If > 0, split long text into chunks of
                    this duration (seconds) and generate chunk by chunk.
                audio_chunk_threshold: Only apply chunking if estimated audio
                    duration exceeds this threshold (seconds).
        Returns:
            ``audios`` a list of 1-D ``np.ndarray`` with shape ``(T,)`` and
            sampling rate consistent with the model's audio tokenizer
            (usually 24 000 Hz).  Can be saved directly with
            ``soundfile.write("out.wav", audios[0], model.sampling_rate)``.
        """

        if self.audio_tokenizer is None or self.text_tokenizer is None:
            raise RuntimeError(
                "Model is not loaded with audio/text tokenizers. Make sure you "
                "loaded the model with OmniVoice.from_pretrained()."
            )
        gen_config = (
            generation_config
            if generation_config is not None
            else OmniVoiceGenerationConfig.from_dict(kwargs)
        )

        self.eval()

        full_task = self._preprocess_all(
            text=text,
            language=language,
            ref_text=ref_text,
            ref_audio=ref_audio,
            voice_clone_prompt=voice_clone_prompt,
            instruct=instruct,
            preprocess_prompt=gen_config.preprocess_prompt,
            speed=speed,
            duration=duration,
        )

        short_idx, long_idx = full_task.get_indices(
            gen_config, self.audio_tokenizer.config.frame_rate
        )

        results = [None] * full_task.batch_size

        if short_idx:
            short_task = full_task.slice_task(short_idx)
            short_results = self._generate_iterative(short_task, gen_config)
            for idx, res in zip(short_idx, short_results):
                results[idx] = res

        if long_idx:
            long_task = full_task.slice_task(long_idx)
            long_results = self._generate_chunked(long_task, gen_config)
            for idx, res in zip(long_idx, long_results):
                results[idx] = res

        generated_audios = []
        for i in range(full_task.batch_size):
            assert results[i] is not None, f"Result {i} was not generated"
            generated_audios.append(
                self._decode_and_post_process(
                    results[i], full_task.ref_rms[i], gen_config  # type: ignore[arg-type]
                )
            )

        return generated_audios

