/*
 * JNI bridge from Mp3Encoder.kt to LAME 3.100 (PIYA-211).
 *
 * Kept in its own library (libpiyanota_lame.so) that links against
 * libmp3lame.so, so LAME itself stays a separately replaceable shared
 * library as the LGPL asks. See THIRD_PARTY_NOTICES.md.
 */
#include <jni.h>
#include <stdint.h>
#include <lame.h>

#define JNI_FN(name) \
    Java_com_piyanota_piyanota_1application_export_Mp3Encoder_##name

JNIEXPORT jlong JNICALL JNI_FN(nativeInit)(JNIEnv *env, jobject self,
                                           jint sample_rate, jint channels,
                                           jint kbps, jint quality) {
    (void)env;
    (void)self;
    lame_global_flags *gfp = lame_init();
    if (gfp == NULL) return 0;
    lame_set_in_samplerate(gfp, sample_rate);
    lame_set_out_samplerate(gfp, sample_rate);
    lame_set_num_channels(gfp, channels);
    lame_set_mode(gfp, channels == 1 ? MONO : JOINT_STEREO);
    /* User decision 2026-10-17: constant bit rate. */
    lame_set_VBR(gfp, vbr_off);
    lame_set_brate(gfp, kbps);
    lame_set_quality(gfp, quality);
    /*
     * The streaming API cannot go back and fill in LAME's Xing/Info header
     * frame, and a CBR file does not need one, so leave it out rather
     * than write a stale placeholder.
     */
    lame_set_bWriteVbrTag(gfp, 0);
    if (lame_init_params(gfp) < 0) {
        lame_close(gfp);
        return 0;
    }
    return (jlong)(intptr_t)gfp;
}

JNIEXPORT jint JNICALL JNI_FN(nativeEncode)(JNIEnv *env, jobject self,
                                            jlong handle, jshortArray pcm,
                                            jint frames, jbyteArray out) {
    (void)self;
    lame_global_flags *gfp = (lame_global_flags *)(intptr_t)handle;
    if (gfp == NULL) return -1;
    jshort *in = (*env)->GetShortArrayElements(env, pcm, NULL);
    jbyte *buf = (*env)->GetByteArrayElements(env, out, NULL);
    if (in == NULL || buf == NULL) {
        if (in != NULL) (*env)->ReleaseShortArrayElements(env, pcm, in, JNI_ABORT);
        if (buf != NULL) (*env)->ReleaseByteArrayElements(env, out, buf, JNI_ABORT);
        return -1;
    }
    jsize size = (*env)->GetArrayLength(env, out);
    int n;
    if (lame_get_num_channels(gfp) == 1) {
        n = lame_encode_buffer(gfp, in, NULL, frames, (unsigned char *)buf, size);
    } else {
        n = lame_encode_buffer_interleaved(gfp, in, frames, (unsigned char *)buf, size);
    }
    (*env)->ReleaseShortArrayElements(env, pcm, in, JNI_ABORT);
    (*env)->ReleaseByteArrayElements(env, out, buf, 0);
    return n;
}

JNIEXPORT jint JNICALL JNI_FN(nativeFlush)(JNIEnv *env, jobject self,
                                           jlong handle, jbyteArray out) {
    (void)self;
    lame_global_flags *gfp = (lame_global_flags *)(intptr_t)handle;
    if (gfp == NULL) return -1;
    jbyte *buf = (*env)->GetByteArrayElements(env, out, NULL);
    if (buf == NULL) return -1;
    jsize size = (*env)->GetArrayLength(env, out);
    int n = lame_encode_flush(gfp, (unsigned char *)buf, size);
    (*env)->ReleaseByteArrayElements(env, out, buf, 0);
    return n;
}

JNIEXPORT void JNICALL JNI_FN(nativeClose)(JNIEnv *env, jobject self,
                                           jlong handle) {
    (void)env;
    (void)self;
    lame_global_flags *gfp = (lame_global_flags *)(intptr_t)handle;
    if (gfp != NULL) lame_close(gfp);
}
