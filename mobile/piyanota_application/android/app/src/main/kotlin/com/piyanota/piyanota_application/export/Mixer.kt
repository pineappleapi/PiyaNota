package com.piyanota.piyanota_application.export

import androidx.annotation.OptIn
import androidx.media3.common.audio.AudioProcessor
import androidx.media3.common.audio.SonicAudioProcessor
import androidx.media3.common.util.UnstableApi
import java.io.BufferedInputStream
import java.io.File
import java.io.FileInputStream
import java.io.InputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.abs
import kotlin.math.roundToInt

/** One decoded track (stereo PCM from [PcmDecoder]) and its mixer gain. */
internal class MixInput(val pcm: File, val gain: Float)

/**
 * Time-stretches each decoded track on its own, mixes them and hands
 * 16-bit stereo frames to [sink].
 *
 * Each track gets its own Sonic instance at the same speed, the way
 * Playback runs one player (so one Sonic) per voice and one for the
 * click, and the gains are applied after the stretch, as player volume
 * is. Sonic over the summed mix is not the same signal: its WSOLA splice
 * points follow the pitch of whatever it is fed, so one Sonic over four
 * voices would not match what Playback plays.
 *
 * The Sonic instances run in lockstep, in memory: each pass reads a chunk
 * of every decoded file, stretches it, and keeps only what has not yet
 * been mixed in a small per-track queue. No stretched audio is written to
 * disk, so temp space stays at the decoded files whatever the speed (a
 * slow speed makes the stretched audio several times longer than the
 * decoded audio). Every track starts at frame 0, so voices and click stay
 * sample-aligned, and the mix runs to the end of the longest stretched
 * track; a track that has ended is silence from then on.
 *
 * Two passes: the first finds the peak of the summed signal and throws
 * the audio away, the second stretches again with fresh Sonic instances
 * and scales the sum down to [PEAK_CEILING] if it is louder (a quieter
 * mix is left as the Mixer set it). Sonic is deterministic, and both
 * passes feed it the same chunks, so the second pass reproduces the
 * first exactly. Four loud voices plus the click can sum past full
 * scale; one fixed gain for the whole file keeps the balance the singer
 * set in the Voice Mixer, where a sample-by-sample limiter would pump.
 */
internal object Mixer {
    /** Frames per mixed chunk, and per read from each decoded file. */
    internal const val CHUNK_FRAMES = 4096
    private const val FULL_SCALE = 32768f
    private const val UNITY_SPEED = 1f
    private const val BYTES_PER_SAMPLE = 2

    /**
     * About -1 dBFS (10^(-1/20)). The peak is measured after the stretch,
     * but MP3 encoding adds its own small overshoots, so a mix peaking at
     * exactly full scale would still clip; the loudest sample is held just
     * below it.
     */
    internal const val PEAK_CEILING = 0.891f

    /**
     * Sonic reports itself inactive (and then drops input) within this
     * distance of 1.0, so such a speed is treated as unity and Sonic is
     * skipped for every track. Compared on the Float Sonic is given, so a
     * Double that only rounds to 1f is unity too.
     */
    private const val SONIC_CLOSENESS = 1e-4f

    /**
     * [progress], when given, gets one stage per pass, counted in decoded
     * frames read (see [RenderProgress]).
     */
    fun mix(
        inputs: List<MixInput>,
        speed: Double,
        sink: (ShortArray, Int) -> Unit,
        progress: RenderProgress? = null,
        cancelled: () -> Boolean,
    ) {
        val asFloat = speed.toFloat()
        val stretch = if (abs(asFloat - UNITY_SPEED) < SONIC_CLOSENESS) null else asFloat
        val decodedFrames = inputs.sumOf { it.pcm.length() / PcmDecoder.BYTES_PER_FRAME }
        val onRead: (Long) -> Unit = { progress?.advance(it) }
        progress?.begin(RenderProgress.PEAK_PASS, decodedFrames)
        val peak = scan(inputs, stretch, cancelled, onRead) { _, _ -> }
        val scale = PEAK_CEILING / maxOf(PEAK_CEILING, peak)
        // The sink (Mp3Encoder.encode) consumes the frames before
        // returning, so one buffer serves every chunk.
        val out = ShortArray(CHUNK_FRAMES * PcmDecoder.OUT_CHANNELS)
        progress?.begin(RenderProgress.ENCODE_PASS, decodedFrames)
        scan(inputs, stretch, cancelled, onRead) { mixed, frames ->
            for (i in 0 until frames * PcmDecoder.OUT_CHANNELS) {
                out[i] = (mixed[i] * scale * Short.MAX_VALUE).roundToInt()
                    .coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt()).toShort()
            }
            sink(out, frames)
        }
    }

    /**
     * One lockstep pass: every track (stretched by [speed], or as decoded
     * when it is null) is summed with its gain, as floats in -1..1 so the
     * sum can exceed 1, and each chunk goes to [onChunk]. Returns the
     * largest absolute summed sample.
     */
    private fun scan(
        inputs: List<MixInput>,
        speed: Float?,
        cancelled: () -> Boolean,
        onRead: (Long) -> Unit,
        onChunk: (FloatArray, Int) -> Unit,
    ): Float {
        val lanes = mutableListOf<Lane>()
        try {
            inputs.forEach { lanes += Lane(it, speed, onRead) }
            val mixed = FloatArray(CHUNK_FRAMES * PcmDecoder.OUT_CHANNELS)
            var peak = 0f
            while (true) {
                if (cancelled()) throw ExportCancelled()
                // Topping every lane up to a full chunk means a chunk is
                // only short once every track has ended, which is the end
                // of the mix.
                for (lane in lanes) {
                    while (!lane.ended && lane.availableFrames < CHUNK_FRAMES) lane.pump()
                }
                val frames = minOf(CHUNK_FRAMES, lanes.maxOfOrNull { it.availableFrames } ?: 0)
                if (frames == 0) break
                mixed.fill(0f)
                for (lane in lanes) lane.takeInto(mixed, frames)
                for (i in 0 until frames * PcmDecoder.OUT_CHANNELS) {
                    peak = maxOf(peak, abs(mixed[i]))
                }
                onChunk(mixed, frames)
            }
            return peak
        } finally {
            lanes.forEach { it.close() }
        }
    }

    private fun readFully(stream: InputStream, into: ByteArray): Int {
        var total = 0
        while (total < into.size) {
            val n = stream.read(into, total, into.size - total)
            if (n < 0) break
            total += n
        }
        return total
    }

    /**
     * One track in a pass: its decoded file, its own Sonic (pitch-kept
     * speed change, FR-9, the same WSOLA implementation ExoPlayer applies
     * to each player in Playback) and a queue of samples not yet mixed.
     * The queue only ever holds under one chunk plus what Sonic returned
     * for the last chunk read, and its buffers are reused.
     */
    @OptIn(UnstableApi::class)
    private class Lane(
        private val input: MixInput,
        speed: Float?,
        private val onRead: (Long) -> Unit,
    ) {
        private val sonic: SonicAudioProcessor? = speed?.let { s ->
            SonicAudioProcessor().apply {
                setSpeed(s)
                setPitch(1f)
                configure(
                    AudioProcessor.AudioFormat(
                        PcmDecoder.OUT_RATE,
                        PcmDecoder.OUT_CHANNELS,
                        android.media.AudioFormat.ENCODING_PCM_16BIT,
                    ),
                )
                // configure() only stages the format; flush() applies it.
                // The metadata overload: from media3 1.8 Sonic implements only
                // that one, and the no-argument flush() throws.
                flush(AudioProcessor.StreamMetadata.DEFAULT)
            }
        }
        // Opened after Sonic, so a Sonic that fails to set up leaks no file.
        private val stream: InputStream = BufferedInputStream(FileInputStream(input.pcm))
        private val bytes = ByteArray(CHUNK_FRAMES * PcmDecoder.BYTES_PER_FRAME)

        // Sonic reads shorts in the buffer's own byte order, so the file's
        // little-endian order is stated, not assumed.
        private val queue = ByteBuffer.allocateDirect(bytes.size).order(ByteOrder.LITTLE_ENDIAN)
        private var fifo = ShortArray(bytes.size / BYTES_PER_SAMPLE)
        private var head = 0
        private var tail = 0

        /** The file is read to its end and Sonic fully drained. */
        var ended = false
            private set

        val availableFrames: Int get() = (tail - head) / PcmDecoder.OUT_CHANNELS

        /** Reads one chunk of the file and queues what it yields. */
        fun pump() {
            val n = readFully(stream, bytes)
            // A trailing partial frame is dropped, as the decoder never
            // writes one.
            val whole = n - n % PcmDecoder.BYTES_PER_FRAME
            val atEnd = n < bytes.size
            if (whole > 0) onRead((whole / PcmDecoder.BYTES_PER_FRAME).toLong())
            if (sonic == null) {
                if (whole > 0) {
                    val shorts = ByteBuffer.wrap(bytes, 0, whole).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer()
                    val count = shorts.remaining()
                    shorts.get(room(count), tail, count)
                    tail += count
                }
                if (atEnd) ended = true
                return
            }
            if (whole > 0) {
                queue.clear()
                queue.put(bytes, 0, whole)
                queue.flip()
                // queueInput takes the whole buffer, so it is free to refill
                // on the next chunk.
                sonic.queueInput(queue)
                drain(sonic)
            }
            if (atEnd) {
                sonic.queueEndOfStream()
                while (!sonic.isEnded) {
                    if (!drain(sonic)) break
                }
                ended = true
            }
        }

        /**
         * Adds up to [frames] queued frames, times the gain, into [mixed].
         * Past what is queued the lane adds nothing: an ended track is
         * silence, and a live one always has a full chunk queued.
         */
        fun takeInto(mixed: FloatArray, frames: Int) {
            val count = minOf(frames * PcmDecoder.OUT_CHANNELS, tail - head)
            for (i in 0 until count) {
                mixed[i] += fifo[head + i] / FULL_SCALE * input.gain
            }
            head += count
        }

        fun close() {
            runCatching { stream.close() }
            sonic?.reset()
        }

        /** Returns whether Sonic had any output. */
        private fun drain(sonic: SonicAudioProcessor): Boolean {
            val out = sonic.output.order(ByteOrder.nativeOrder())
            val count = out.remaining() / BYTES_PER_SAMPLE
            if (count == 0) return false
            out.asShortBuffer().get(room(count), tail, count)
            tail += count
            return true
        }

        /**
         * Makes space for [count] more samples at [tail]: mixed samples are
         * dropped from the front first, and the array only grows when the
         * unmixed ones plus [count] do not fit.
         */
        private fun room(count: Int): ShortArray {
            if (tail + count <= fifo.size) return fifo
            val live = tail - head
            if (live + count > fifo.size) {
                val grown = ShortArray(maxOf(live + count, fifo.size * 2))
                System.arraycopy(fifo, head, grown, 0, live)
                fifo = grown
            } else {
                System.arraycopy(fifo, head, fifo, 0, live)
            }
            head = 0
            tail = live
            return fifo
        }
    }
}
