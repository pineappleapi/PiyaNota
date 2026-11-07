/* MIDI -> mono 22050 Hz 16-bit WAV via FluidSynth (reverb/chorus off).
 * Called from Dart over dart:ffi, so no JNI and no global state. */
#include <fluidsynth.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define SAMPLE_RATE 22050
#define BLOCK_FRAMES 4096
#define WAV_HEADER_BYTES 44

#define ERR_SETTINGS 1
#define ERR_SYNTH 2
#define ERR_SFLOAD 3
#define ERR_PLAYER 4
#define ERR_PLAYER_ADD 5
#define ERR_FILE_OPEN 6
#define ERR_WRITE 7

static void put32(unsigned char *p, uint32_t v) {
    p[0] = v & 0xff; p[1] = (v >> 8) & 0xff; p[2] = (v >> 16) & 0xff; p[3] = (v >> 24) & 0xff;
}
static void put16(unsigned char *p, uint16_t v) { p[0] = v & 0xff; p[1] = (v >> 8) & 0xff; }

static void make_header(unsigned char *h, uint32_t data_bytes) {
    memcpy(h, "RIFF", 4); put32(h + 4, 36 + data_bytes);
    memcpy(h + 8, "WAVEfmt ", 8); put32(h + 16, 16);
    put16(h + 20, 1); put16(h + 22, 1);            /* PCM, mono */
    put32(h + 24, SAMPLE_RATE); put32(h + 28, SAMPLE_RATE * 2);
    put16(h + 32, 2); put16(h + 34, 16);
    memcpy(h + 36, "data", 4); put32(h + 40, data_bytes);
}

int piya_render(const char *sf2, const char *mid, const char *wav_out, int *peak_out) {
    int rc = 0;
    fluid_settings_t *s = NULL;
    fluid_synth_t *sy = NULL;
    fluid_player_t *p = NULL;
    FILE *f = NULL;
    if (peak_out) *peak_out = 0;

    s = new_fluid_settings();
    if (!s) return ERR_SETTINGS;
    fluid_settings_setint(s, "synth.reverb.active", 0);
    fluid_settings_setint(s, "synth.chorus.active", 0);
    fluid_settings_setnum(s, "synth.sample-rate", SAMPLE_RATE);
    sy = new_fluid_synth(s);
    if (!sy) { rc = ERR_SYNTH; goto done; }
    if (fluid_synth_sfload(sy, sf2, 1) < 0) { rc = ERR_SFLOAD; goto done; }
    p = new_fluid_player(sy);
    if (!p) { rc = ERR_PLAYER; goto done; }
    if (fluid_player_add(p, mid) != FLUID_OK) { rc = ERR_PLAYER_ADD; goto done; }
    f = fopen(wav_out, "wb");
    if (!f) { rc = ERR_FILE_OPEN; goto done; }

    unsigned char hdr[WAV_HEADER_BYTES] = {0};
    if (fwrite(hdr, 1, WAV_HEADER_BYTES, f) != WAV_HEADER_BYTES) { rc = ERR_WRITE; goto done; }
    fluid_player_play(p);
    int16_t st[2 * BLOCK_FRAMES], mono[BLOCK_FRAMES];
    uint32_t frames = 0;
    int peak = 0;
    while (fluid_player_get_status(p) == FLUID_PLAYER_PLAYING) {
        fluid_synth_write_s16(sy, BLOCK_FRAMES, st, 0, 2, st, 1, 2);
        for (int i = 0; i < BLOCK_FRAMES; i++) {
            int m = ((int)st[2 * i] + (int)st[2 * i + 1]) / 2;
            mono[i] = (int16_t)m;
            int a = abs(m);
            if (a > peak) peak = a;
        }
        if (fwrite(mono, 2, BLOCK_FRAMES, f) != BLOCK_FRAMES) { rc = ERR_WRITE; goto done; }
        frames += BLOCK_FRAMES;
    }
    make_header(hdr, frames * 2);
    rewind(f);
    if (fwrite(hdr, 1, WAV_HEADER_BYTES, f) != WAV_HEADER_BYTES) rc = ERR_WRITE;
    if (peak_out) *peak_out = peak;
done:
    if (f && fclose(f) != 0 && rc == 0) rc = ERR_WRITE;
    if (p) delete_fluid_player(p);
    if (sy) delete_fluid_synth(sy);
    if (s) delete_fluid_settings(s);
    return rc;
}
