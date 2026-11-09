package com.piyanota.piyanota_application.export

import java.io.Closeable
import java.io.OutputStream

/**
 * Thin wrapper over LAME 3.100 (LGPL, loaded as its own shared library
 * so it can be replaced, see THIRD_PARTY_NOTICES.md). Android has no
 * built-in MP3 encoder, and the user decided the export is MP3.
 */
internal class Mp3Encoder(
    sampleRate: Int,
    channels: Int,
    private val out: OutputStream,
) : Closeable {
    private var handle: Long

    init {
        ensureLoaded()
        handle = nativeInit(sampleRate, channels, BITRATE_KBPS, QUALITY)
        if (handle == 0L) throw EncoderUnavailable("lame_init_params failed")
    }

    private var buffer = ByteArray(0)

    /** [frames] interleaved stereo frames from [pcm]. */
    fun encode(pcm: ShortArray, frames: Int) {
        val needed = mp3BufferSize(frames)
        if (buffer.size < needed) buffer = ByteArray(needed)
        val n = nativeEncode(handle, pcm, frames, buffer)
        if (n < 0) throw EncoderUnavailable("lame_encode_buffer_interleaved returned $n")
        out.write(buffer, 0, n)
    }

    fun finish() {
        if (buffer.size < FLUSH_BUFFER_BYTES) buffer = ByteArray(FLUSH_BUFFER_BYTES)
        val n = nativeFlush(handle, buffer)
        if (n < 0) throw EncoderUnavailable("lame_encode_flush returned $n")
        out.write(buffer, 0, n)
    }

    override fun close() {
        if (handle != 0L) {
            nativeClose(handle)
            handle = 0L
        }
    }

    private external fun nativeInit(sampleRate: Int, channels: Int, kbps: Int, quality: Int): Long
    private external fun nativeEncode(handle: Long, pcm: ShortArray, frames: Int, out: ByteArray): Int
    private external fun nativeFlush(handle: Long, out: ByteArray): Int
    private external fun nativeClose(handle: Long)

    /** LAME is missing or failed; reported as `generation_failed`. */
    class EncoderUnavailable(message: String, cause: Throwable? = null) : RuntimeException(message, cause)

    companion object {
        /** User decision 2026-10-17: 192 kbps CBR. */
        const val BITRATE_KBPS = 192

        /** LAME's "high quality" preset point; 0 is several times slower for no audible gain. */
        private const val QUALITY = 2

        /** LAME's documented worst case: 1.25 × samples + 7200. */
        private fun mp3BufferSize(frames: Int): Int = frames * 5 / 4 + 7200

        private const val FLUSH_BUFFER_BYTES = 7200

        @Volatile
        private var loaded = false

        /**
         * Loads LAME, or throws [EncoderUnavailable]. Called by the export
         * before it decodes anything, so a missing library fails at once.
         */
        @Synchronized
        fun ensureLoaded() {
            if (loaded) return
            try {
                // mp3lame first: the JNI wrapper links against it, and older
                // Android linkers do not resolve app-private dependencies.
                System.loadLibrary("mp3lame")
                System.loadLibrary("piyanota_lame")
                loaded = true
            } catch (e: UnsatisfiedLinkError) {
                throw EncoderUnavailable("LAME native library not in this build", e)
            }
        }
    }
}
