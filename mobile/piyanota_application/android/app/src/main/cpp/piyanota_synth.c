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
#define SYNTH_GAIN 0.8
/* Extra render after the last event so release tails are not cut. */
#define TAIL_BLOCKS ((SAMPLE_RATE + BLOCK_FRAMES - 1) / BLOCK_FRAMES)

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
    fluid_settings_setnum(s, "synth.gain", SYNTH_GAIN);
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
    int tail = 0;
    while (fluid_player_get_status(p) == FLUID_PLAYER_PLAYING || tail < TAIL_BLOCKS) {
        fluid_synth_write_s16(sy, BLOCK_FRAMES, st, 0, 2, st, 1, 2);
        for (int i = 0; i < BLOCK_FRAMES; i++) {
            int m = ((int)st[2 * i] + (int)st[2 * i + 1]) / 2;
            mono[i] = (int16_t)m;
            int a = abs(m);
            if (a > peak) peak = a;
        }
        if (fwrite(mono, 2, BLOCK_FRAMES, f) != BLOCK_FRAMES) { rc = ERR_WRITE; goto done; }
        frames += BLOCK_FRAMES;
        if (fluid_player_get_status(p) != FLUID_PLAYER_PLAYING) tail++;
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

/* ---- Live playback: one synth, one player, one audio output (one clock) ----
 * Replaces five independent just_audio players, whose drift needed audible
 * re-seeks. Per-voice level is MIDI CC7 on the voice's channel. The tempo is
 * already in the file (Dart scales it), so there is no tempo API here. */
#define LIVE_SAMPLE_RATE 44100
#define LIVE_ERR_DRIVER 8
#define LIVE_CC_VOLUME 7
#define LIVE_CC_MAX 127

typedef struct {
    fluid_settings_t *settings;
    fluid_synth_t *synth;
    fluid_player_t *player;
    fluid_audio_driver_t *driver;
    char *mid;
} piya_live;

void piya_live_close(piya_live *h) {
    if (!h) return;
    if (h->driver) delete_fluid_audio_driver(h->driver);
    if (h->player) delete_fluid_player(h->player);
    if (h->synth) delete_fluid_synth(h->synth);
    if (h->settings) delete_fluid_settings(h->settings);
    free(h->mid);
    free(h);
}

/* Returns NULL on failure with the ERR_* / LIVE_ERR_DRIVER code in *err. */
piya_live *piya_live_open(const char *sf2, const char *mid, int *err) {
    int rc = 0;
    piya_live *h = calloc(1, sizeof(piya_live));
    if (!h) { if (err) *err = ERR_SETTINGS; return NULL; }
    h->mid = strdup(mid);
    h->settings = new_fluid_settings();
    if (!h->settings || !h->mid) { rc = ERR_SETTINGS; goto fail; }
    fluid_settings_setint(h->settings, "synth.reverb.active", 0);
    fluid_settings_setint(h->settings, "synth.chorus.active", 0);
    fluid_settings_setnum(h->settings, "synth.sample-rate", LIVE_SAMPLE_RATE);
    fluid_settings_setnum(h->settings, "synth.gain", SYNTH_GAIN);
    fluid_settings_setstr(h->settings, "audio.driver", "oboe");
    h->synth = new_fluid_synth(h->settings);
    if (!h->synth) { rc = ERR_SYNTH; goto fail; }
    if (fluid_synth_sfload(h->synth, sf2, 1) < 0) { rc = ERR_SFLOAD; goto fail; }
    h->player = new_fluid_player(h->synth);
    if (!h->player) { rc = ERR_PLAYER; goto fail; }
    if (fluid_player_add(h->player, mid) != FLUID_OK) { rc = ERR_PLAYER_ADD; goto fail; }
    /* Last: the driver starts pulling audio at once (silence until play). */
    h->driver = new_fluid_audio_driver(h->settings, h->synth);
    if (!h->driver) { rc = LIVE_ERR_DRIVER; goto fail; }
    if (err) *err = 0;
    return h;
fail:
    if (err) *err = rc;
    piya_live_close(h);
    return NULL;
}

/* A finished player cannot be restarted reliably across FluidSynth versions
 * (its playlist is spent), so play-from-the-end builds a fresh one. */
int piya_live_reset(piya_live *h) {
    fluid_synth_all_sounds_off(h->synth, -1);
    fluid_player_t *p = new_fluid_player(h->synth);
    if (!p) return ERR_PLAYER;
    if (fluid_player_add(p, h->mid) != FLUID_OK) { delete_fluid_player(p); return ERR_PLAYER_ADD; }
    delete_fluid_player(h->player);
    h->player = p;
    return 0;
}

int piya_live_play(piya_live *h) { return fluid_player_play(h->player); }

/* Stop leaves the tick where it was; notes already sounding are cut. */
int piya_live_pause(piya_live *h) {
    int rc = fluid_player_stop(h->player);
    fluid_synth_all_sounds_off(h->synth, -1);
    return rc;
}

int piya_live_seek(piya_live *h, int tick) {
    fluid_synth_all_sounds_off(h->synth, -1);
    return fluid_player_seek(h->player, tick);
}

int piya_live_tick(piya_live *h) { return fluid_player_get_current_tick(h->player); }
int piya_live_total_ticks(piya_live *h) { return fluid_player_get_total_ticks(h->player); }
int piya_live_is_playing(piya_live *h) {
    return fluid_player_get_status(h->player) == FLUID_PLAYER_PLAYING;
}

/* Level 0..127 on one channel; CC7 is squared by the synth, the caller maps. */
void piya_live_set_level(piya_live *h, int channel, int level) {
    if (level < 0) level = 0;
    if (level > LIVE_CC_MAX) level = LIVE_CC_MAX;
    fluid_synth_cc(h->synth, channel, LIVE_CC_VOLUME, level);
}
