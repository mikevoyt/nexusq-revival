#!/bin/sh

NQ_AUDIO_DIAG_BASE_REQUIRED_ARGS="${NQ_AUDIO_DIAG_BASE_REQUIRED_ARGS:-nq.audio_format=i2s nq.audio_inversion=nb-nf nq.steelhead_audio_dump=1 nq.tas571x_dump_regs=1 nq.tas571x_legacy_stream_reinit=1 nq.mcbsp_legacy_element=1 nq.mcbsp_legacy_threshold_frame=1 nq.mcbsp_legacy_tx_irq=1 nq.mcbsp_no_rx_err_irq=1}"
NQ_AUDIO_DIAG_LEGACY_DMA_REQUIRED_ARGS="${NQ_AUDIO_DIAG_LEGACY_DMA_REQUIRED_ARGS:-$NQ_AUDIO_DIAG_BASE_REQUIRED_ARGS nq.omap_dma_legacy_cyclic_sync=1 nq.omap_dma_legacy_cyclic_burst=1 nq.omap_dma_legacy_cyclic_pack=1 nq.omap_dma_dump_cyclic=1}"
NQ_AUDIO_DIAG_REQUIRED_ARGS="${NQ_AUDIO_DIAG_REQUIRED_ARGS:-$NQ_AUDIO_DIAG_LEGACY_DMA_REQUIRED_ARGS}"
