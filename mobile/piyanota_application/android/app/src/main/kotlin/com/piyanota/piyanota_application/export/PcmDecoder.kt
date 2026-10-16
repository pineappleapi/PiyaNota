package com.piyanota.piyanota_application.export

import android.media.AudioFormat
import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import java.io.BufferedOutputStream
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Decodes one track to raw 16-bit little-endian stereo PCM at
 * [OUT_RATE], so the mixer can add tracks sample by sample.
 *
 * The result goes to a file, not memory: a four-minute track is ~42 MB
 * as stereo PCM, and an export can hold five of them (four voices and
 * the click), which would not fit a low-end phone's heap.
 */
internal object PcmDecoder {
    const val OUT_RATE = 44_100
    const val OUT_CHANNELS = 2
    const val BYTES_PER_FRAME = OUT_CHANNELS * 2

    private const val CODEC_TIMEOUT_US = 10_000L
    private const val PCM_FORMAT_TAG = 1
    private const val PCM_16_BITS = 16
    private const val FMT_CHUNK_BYTES = 16
    private const val IO_CHUNK_BYTES = 64 * 1024

    /** Returns the number of stereo frames written to [out]. */
    fun decode(src: File, out: File, cancelled: () -> Boolean): Long {
        BufferedOutputStream(FileOutputStream(out), IO_CHUNK_BYTES).use { sink ->
            val writer = FrameWriter(sink)
            // The click track and the demo voices are plain PCM WAV. Reading
            // them directly avoids depending on the platform's audio/raw
            // decoder, which is not on every device.
            val wav = readWavHeader(src)
            if (wav != null) {
                decodeWav(src, wav, writer, cancelled)
            } else {
                decodeWithMediaCodec(src, writer, cancelled)
            }
            writer.finish()
            return writer.frames
        }
    }

    private class WavInfo(
        val channels: Int,
        val rate: Int,
        val dataOffset: Long,
        val dataBytes: Long,
    )

    /** Null unless [src] is a 16-bit PCM RIFF/WAVE file. */
    private fun readWavHeader(src: File): WavInfo? {
        RandomAccessFile(src, "r").use { f ->
            val head = ByteArray(12)
            if (f.read(head) != head.size) return null
            if (String(head, 0, 4, Charsets.US_ASCII) != "RIFF" ||
                String(head, 8, 4, Charsets.US_ASCII) != "WAVE"
            ) {
                return null
            }
            var channels = 0
            var rate = 0
            var bits = 0
            var tag = 0
            val chunk = ByteArray(8)
            while (f.read(chunk) == chunk.size) {
                val id = String(chunk, 0, 4, Charsets.US_ASCII)
                val size = ByteBuffer.wrap(chunk, 4, 4).order(ByteOrder.LITTLE_ENDIAN).int
                    .toLong() and 0xFFFFFFFFL
                // RIFF pads odd-sized chunks to an even length.
                val padded = size + (size and 1L)
                when (id) {
                    "fmt " -> {
                        if (size < FMT_CHUNK_BYTES) return null
                        val fmt = ByteArray(FMT_CHUNK_BYTES)
                        if (f.read(fmt) != fmt.size) return null
                        val b = ByteBuffer.wrap(fmt).order(ByteOrder.LITTLE_ENDIAN)
                        tag = b.short.toInt()
                        channels = b.short.toInt()
                        rate = b.int
                        b.int // byte rate
                        b.short // block align
                        bits = b.short.toInt()
                        f.seek(f.filePointer + padded - FMT_CHUNK_BYTES)
                    }
                    "data" -> {
                        if (tag != PCM_FORMAT_TAG || bits != PCM_16_BITS || channels <= 0 || rate <= 0) {
                            return null
                        }
                        val available = f.length() - f.filePointer
                        return WavInfo(channels, rate, f.filePointer, minOf(size, available))
                    }
                    else -> f.seek(f.filePointer + padded)
                }
            }
            return null
        }
    }

    private fun decodeWav(src: File, wav: WavInfo, writer: FrameWriter, cancelled: () -> Boolean) {
        val resampler = StereoResampler(wav.rate, wav.channels, writer)
        RandomAccessFile(src, "r").use { f ->
            f.seek(wav.dataOffset)
            val frameBytes = wav.channels * 2
            val buf = ByteArray(IO_CHUNK_BYTES - IO_CHUNK_BYTES % frameBytes)
            var left = wav.dataBytes - wav.dataBytes % frameBytes
            while (left > 0) {
                if (cancelled()) throw ExportCancelled()
                val n = f.read(buf, 0, minOf(buf.size.toLong(), left).toInt())
                if (n <= 0) break
                val whole = n - n % frameBytes
                resampler.feed16(ByteBuffer.wrap(buf, 0, whole).slice().order(ByteOrder.LITTLE_ENDIAN))
                left -= n
            }
        }
        resampler.finish()
    }

    private fun decodeWithMediaCodec(src: File, writer: FrameWriter, cancelled: () -> Boolean) {
        val extractor = MediaExtractor()
        var codec: MediaCodec? = null
        try {
            extractor.setDataSource(src.path)
            val track = (0 until extractor.trackCount).firstOrNull {
                extractor.getTrackFormat(it).getString(MediaFormat.KEY_MIME)?.startsWith("audio/") == true
            } ?: throw IOException("no audio track in ${src.name}")
            extractor.selectTrack(track)
            val inFormat = extractor.getTrackFormat(track)
            val mime = inFormat.getString(MediaFormat.KEY_MIME)
                ?: throw IOException("no mime type in ${src.name}")
            val c = MediaCodec.createDecoderByType(mime)
            codec = c
            c.configure(inFormat, null, null, 0)
            c.start()

            var encoding = AudioFormat.ENCODING_PCM_16BIT
            var resampler = StereoResampler(
                inFormat.getInteger(MediaFormat.KEY_SAMPLE_RATE),
                inFormat.getInteger(MediaFormat.KEY_CHANNEL_COUNT),
                writer,
            )
            val info = MediaCodec.BufferInfo()
            var inputDone = false
            while (true) {
                if (cancelled()) throw ExportCancelled()
                if (!inputDone) {
                    val i = c.dequeueInputBuffer(CODEC_TIMEOUT_US)
                    if (i >= 0) {
                        val buffer = c.getInputBuffer(i) ?: throw IOException("no codec input buffer")
                        val n = extractor.readSampleData(buffer, 0)
                        if (n < 0) {
                            c.queueInputBuffer(i, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM)
                            inputDone = true
                        } else {
                            c.queueInputBuffer(i, 0, n, extractor.sampleTime, 0)
                            extractor.advance()
                        }
                    }
                }
                val o = c.dequeueOutputBuffer(info, CODEC_TIMEOUT_US)
                if (o == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    // The decoder's real output can differ from the container's
                    // claim (HE-AAC doubles the rate, for one), so rebuild here.
                    val f = c.outputFormat
                    encoding = if (f.containsKey(MediaFormat.KEY_PCM_ENCODING)) {
                        f.getInteger(MediaFormat.KEY_PCM_ENCODING)
                    } else {
                        AudioFormat.ENCODING_PCM_16BIT
                    }
                    resampler.finish()
                    resampler = StereoResampler(
                        f.getInteger(MediaFormat.KEY_SAMPLE_RATE),
                        f.getInteger(MediaFormat.KEY_CHANNEL_COUNT),
                        writer,
                    )
                } else if (o >= 0) {
                    val out = c.getOutputBuffer(o) ?: throw IOException("no codec output buffer")
                    out.position(info.offset)
                    out.limit(info.offset + info.size)
                    val pcm = out.slice().order(ByteOrder.nativeOrder())
                    when (encoding) {
                        AudioFormat.ENCODING_PCM_16BIT -> resampler.feed16(pcm)
                        AudioFormat.ENCODING_PCM_FLOAT -> resampler.feedFloat(pcm)
                        else -> throw IOException("unsupported PCM encoding $encoding")
                    }
                    c.releaseOutputBuffer(o, false)
                    if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) break
                }
            }
            resampler.finish()
        } finally {
            // Release must run even when decoding failed, or the codec slot
            // leaks until the process dies; a failure here is not the user's
            // problem and must not hide the original error.
            codec?.let { c ->
                runCatching { c.stop() }
                runCatching { c.release() }
            }
            extractor.release()
        }
    }

    /** Buffers stereo frames and writes them little-endian. */
    private class FrameWriter(private val sink: BufferedOutputStream) {
        private val buf = ByteBuffer.allocate(IO_CHUNK_BYTES).order(ByteOrder.LITTLE_ENDIAN)
        var frames = 0L
            private set

        fun write(left: Short, right: Short) {
            if (buf.remaining() < BYTES_PER_FRAME) flush()
            buf.putShort(left)
            buf.putShort(right)
            frames++
        }

        fun finish() = flush()

        private fun flush() {
            sink.write(buf.array(), 0, buf.position())
            buf.clear()
        }
    }

    /**
     * Streaming linear-interpolation resampler to [OUT_RATE] stereo.
     * Linear is enough here: the sources are piano tracks and a click
     * rendered at 22.05/44.1/48 kHz, and the result is encoded at
     * 192 kbps, which hides the interpolation roll-off.
     */
    private class StereoResampler(
        inRate: Int,
        private val channels: Int,
        private val out: FrameWriter,
    ) {
        private val step = inRate.toDouble() / OUT_RATE
        private val passThrough = inRate == OUT_RATE
        private var hasPrev = false
        private var prevL = 0f
        private var prevR = 0f
        private var pos = 0.0

        fun feed16(pcm: ByteBuffer) {
            val sb = pcm.asShortBuffer()
            while (sb.remaining() >= channels) {
                val l = sb.get().toFloat()
                val r = if (channels > 1) sb.get().toFloat() else l
                // Channels past the first two are dropped; the pipeline's
                // tracks are mono or stereo.
                repeat(channels - 2) { sb.get() }
                frame(l, r)
            }
        }

        fun feedFloat(pcm: ByteBuffer) {
            val fb = pcm.asFloatBuffer()
            while (fb.remaining() >= channels) {
                val l = fb.get() * Short.MAX_VALUE
                val r = if (channels > 1) fb.get() * Short.MAX_VALUE else l
                repeat(channels - 2) { fb.get() }
                frame(l, r)
            }
        }

        private fun frame(l: Float, r: Float) {
            if (passThrough) {
                out.write(clamp(l), clamp(r))
                return
            }
            if (!hasPrev) {
                prevL = l
                prevR = r
                hasPrev = true
                return
            }
            // Emit every output frame that falls between prev (0) and this
            // frame (1).
            while (pos < 1.0) {
                val t = pos.toFloat()
                out.write(clamp(prevL + (l - prevL) * t), clamp(prevR + (r - prevR) * t))
                pos += step
            }
            pos -= 1.0
            prevL = l
            prevR = r
        }

        fun finish() {
            if (!passThrough && hasPrev) out.write(clamp(prevL), clamp(prevR))
            hasPrev = false
        }

        private fun clamp(v: Float): Short =
            v.coerceIn(Short.MIN_VALUE.toFloat(), Short.MAX_VALUE.toFloat()).toInt().toShort()
    }
}

/** The export was stopped (activity destroyed); reported as `interrupted`. */
internal class ExportCancelled : RuntimeException("export cancelled")
