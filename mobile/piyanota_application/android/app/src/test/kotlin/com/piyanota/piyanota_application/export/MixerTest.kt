package com.piyanota.piyanota_application.export

import androidx.annotation.OptIn
import androidx.media3.common.audio.AudioProcessor
import androidx.media3.common.audio.SonicAudioProcessor
import androidx.media3.common.util.UnstableApi
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.roundToInt
import kotlin.math.sin

/**
 * The lockstep, in-memory export mixer (PIYA-211 AC23) against a
 * reference that stretches each whole track on its own first, the way
 * the earlier temp-file mixer did: the two must give the same samples.
 */
@OptIn(UnstableApi::class)
class MixerTest {
    @get:Rule
    val tmp = TemporaryFolder()

    private val rate = PcmDecoder.OUT_RATE

    // Lengths chosen off the chunk grid, and different per track, so the
    // short tracks end mid-chunk and must turn into silence.
    private fun tracks(): List<MixInput> = listOf(
        MixInput(tone("s.raw", 220.0, frames = rate * 3 + 123), 0.8f),
        MixInput(tone("a.raw", 330.0, frames = rate * 2 + 4001), 0.5f),
        MixInput(tone("click.raw", 1000.0, frames = rate / 3), 1.0f),
    )

    @Test
    fun slowSpeedMatchesStretchingEachTrackThenSumming() = assertMatchesReference(0.33)

    @Test
    fun fastSpeedMatchesStretchingEachTrackThenSumming() = assertMatchesReference(1.7)

    @Test
    fun verySlowSpeedMatchesStretchingEachTrackThenSumming() = assertMatchesReference(0.125)

    @Test
    fun unitySpeedSumsTheDecodedTracksAsTheyAre() {
        val inputs = tracks()
        val decoded = inputs.map { readShorts(it.pcm) }
        val expected = sumAndScale(decoded, inputs.map { it.gain })
        assertArrayEquals(expected, mixToArray(inputs, 1.0))
        // Within Sonic's closeness of 1.0 counts as unity too.
        assertArrayEquals(expected, mixToArray(inputs, 1.00005))
    }

    @Test
    fun mixRunsToTheEndOfTheLongestStretchedTrack() {
        val inputs = tracks()
        val speed = 0.5
        val out = mixToArray(inputs, speed)
        val longest = inputs.maxOf { stretchWhole(readShorts(it.pcm), speed.toFloat()).size }
        assertEquals(longest, out.size)
        val decodedFrames = readShorts(inputs[0].pcm).size / PcmDecoder.OUT_CHANNELS
        val outFrames = out.size / PcmDecoder.OUT_CHANNELS
        // Sonic's length is the input over the speed, give or take a few
        // pitch periods.
        assertEquals(decodedFrames / speed, outFrames.toDouble(), rate * 0.05)
    }

    @Test
    fun loudMixIsHeldAtTheCeilingAndQuietMixIsLeftAlone() {
        val loud = (0 until 4).map { MixInput(tone("v$it.raw", 220.0 * (it + 1), rate * 2, amplitude = 0.9), 1f) }
        val loudPeak = mixToArray(loud, 0.5).maxOf { abs(it.toInt()) }
        assertEquals((Mixer.PEAK_CEILING * Short.MAX_VALUE).roundToInt().toDouble(), loudPeak.toDouble(), 1.0)

        val quiet = listOf(MixInput(tone("q.raw", 440.0, rate, amplitude = 0.2), 0.5f))
        val quietPeak = mixToArray(quiet, 1.0).maxOf { abs(it.toInt()) }
        assertEquals(0.1 * Short.MAX_VALUE, quietPeak.toDouble(), 2.0)
    }

    @Test
    fun noTempFilesAreWrittenAndTheDecodedFilesAreKept() {
        val inputs = tracks()
        val before = tmp.root.listFiles()!!.map { it.name }.sorted()
        var sawNewFile = false
        Mixer.mix(inputs, 0.33, { _, _ ->
            if (tmp.root.listFiles()!!.size != before.size) sawNewFile = true
        }) { false }
        assertTrue("the mixer wrote a file beside the decoded ones", !sawNewFile)
        assertEquals(before, tmp.root.listFiles()!!.map { it.name }.sorted())
        assertTrue(inputs.all { it.pcm.exists() })
    }

    @Test
    fun everyChunkButTheLastIsFull() {
        val sizes = mutableListOf<Int>()
        Mixer.mix(tracks(), 0.33, { _, frames -> sizes += frames }) { false }
        assertTrue(sizes.dropLast(1).all { it == Mixer.CHUNK_FRAMES })
        assertTrue(sizes.last() in 1..Mixer.CHUNK_FRAMES)
    }

    @Test
    fun cancellingDuringTheSecondPassStopsIt() {
        var chunks = 0
        var cancel = false
        try {
            Mixer.mix(tracks(), 0.33, { _, _ ->
                chunks++
                cancel = true
            }) { cancel }
            fail("expected ExportCancelled")
        } catch (_: ExportCancelled) {
            assertEquals(1, chunks)
        }
    }

    @Test
    fun cancellingDuringThePeakPassWritesNothing() {
        var checks = 0
        var chunks = 0
        try {
            Mixer.mix(tracks(), 0.33, { _, _ -> chunks++ }) { ++checks > 3 }
            fail("expected ExportCancelled")
        } catch (_: ExportCancelled) {
            assertEquals(0, chunks)
        }
    }

    // ---- helpers --------------------------------------------------------

    private fun assertMatchesReference(speed: Double) {
        val inputs = tracks()
        val stretched = inputs.map { stretchWhole(readShorts(it.pcm), speed.toFloat()) }
        val expected = sumAndScale(stretched, inputs.map { it.gain })
        val actual = mixToArray(inputs, speed)
        assertEquals(expected.size, actual.size)
        assertArrayEquals(expected, actual)
    }

    private fun mixToArray(inputs: List<MixInput>, speed: Double): ShortArray {
        val out = ArrayList<Short>()
        Mixer.mix(inputs, speed, { buf, frames ->
            for (i in 0 until frames * PcmDecoder.OUT_CHANNELS) out += buf[i]
        }) { false }
        return out.toShortArray()
    }

    /** Sums with gains, finds the peak, scales: the mixer's arithmetic. */
    private fun sumAndScale(tracks: List<ShortArray>, gains: List<Float>): ShortArray {
        val length = tracks.maxOf { it.size }
        val mixed = FloatArray(length)
        for ((k, t) in tracks.withIndex()) {
            for (i in t.indices) mixed[i] += t[i] / 32768f * gains[k]
        }
        val peak = mixed.maxOfOrNull { abs(it) } ?: 0f
        val scale = Mixer.PEAK_CEILING / maxOf(Mixer.PEAK_CEILING, peak)
        return ShortArray(length) { i ->
            (mixed[i] * scale * Short.MAX_VALUE).roundToInt()
                .coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt()).toShort()
        }
    }

    /** One Sonic over the whole track, fed in the mixer's chunk size. */
    private fun stretchWhole(samples: ShortArray, speed: Float): ShortArray {
        val sonic = SonicAudioProcessor()
        sonic.setSpeed(speed)
        sonic.setPitch(1f)
        sonic.configure(AudioProcessor.AudioFormat(rate, PcmDecoder.OUT_CHANNELS, ENCODING_PCM_16BIT))
        sonic.flush(AudioProcessor.StreamMetadata.DEFAULT)
        val out = ArrayList<Short>()
        fun drain(): Boolean {
            val buf = sonic.output.order(ByteOrder.nativeOrder()).asShortBuffer()
            if (!buf.hasRemaining()) return false
            while (buf.hasRemaining()) out += buf.get()
            return true
        }
        val chunk = Mixer.CHUNK_FRAMES * PcmDecoder.OUT_CHANNELS
        var pos = 0
        while (pos < samples.size) {
            val n = minOf(chunk, samples.size - pos)
            val bb = ByteBuffer.allocateDirect(n * 2).order(ByteOrder.LITTLE_ENDIAN)
            bb.asShortBuffer().put(samples, pos, n)
            sonic.queueInput(bb)
            drain()
            pos += n
        }
        sonic.queueEndOfStream()
        while (!sonic.isEnded) if (!drain()) break
        sonic.reset()
        return out.toShortArray()
    }

    private fun tone(name: String, hz: Double, frames: Int, amplitude: Double = 0.6): File {
        val file = tmp.newFile(name)
        val bb = ByteBuffer.allocate(frames * PcmDecoder.BYTES_PER_FRAME).order(ByteOrder.LITTLE_ENDIAN)
        for (f in 0 until frames) {
            val v = (sin(2 * PI * hz * f / rate) * amplitude * Short.MAX_VALUE).roundToInt().toShort()
            bb.putShort(v).putShort(v)
        }
        file.writeBytes(bb.array())
        return file
    }

    private fun readShorts(file: File): ShortArray {
        val sb = ByteBuffer.wrap(file.readBytes()).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer()
        return ShortArray(sb.remaining()).also { sb.get(it) }
    }

    private companion object {
        /** android.media.AudioFormat.ENCODING_PCM_16BIT. */
        const val ENCODING_PCM_16BIT = 2
    }
}
