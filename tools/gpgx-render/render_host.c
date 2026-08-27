/* Minimal libretro host, just enough to make the core load a ROM.
 *
 * The render hook lives at the end of paprium_init(), which runs during
 * retro_load_game(), so nothing here needs to run frames or present video. The
 * hook writes its WAV and calls exit(0), so this program is not expected to
 * return from retro_load_game at all.
 *
 * Usage: render_host <core.dll> <rom.bin>
 * with PAPRIUM_RENDER="track:seconds:outfile" set.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>
#include <stdint.h>
#include <stdbool.h>

struct retro_game_info {
    const char *path;
    const void *data;
    size_t      size;
    const char *meta;
};

typedef bool (*env_t)(unsigned cmd, void *data);

/* The core asks for a handful of things during init. Refusing everything is
 * fine for our purposes except the pixel format and log interface, which some
 * cores treat as fatal - so answer those and decline the rest. */
static bool environ_cb(unsigned cmd, void *data)
{
    switch (cmd) {
        case 10:  /* SET_PIXEL_FORMAT   */ return true;
        case 9:   /* GET_SYSTEM_DIRECTORY */
        case 31:  /* GET_SAVE_DIRECTORY */
            *(const char **)data = ".";
            return true;
        default:
            return false;
    }
}

static void video_cb(const void *d, unsigned w, unsigned h, size_t p) { (void)d;(void)w;(void)h;(void)p; }
static void audio_cb(int16_t l, int16_t r) { (void)l;(void)r; }
static size_t audio_batch_cb(const int16_t *d, size_t f) { (void)d; return f; }
static void input_poll_cb(void) {}
static int16_t input_state_cb(unsigned a, unsigned b, unsigned c, unsigned d)
{ (void)a;(void)b;(void)c;(void)d; return 0; }

#define SYM(name) do {                                                    \
        *(FARPROC *)&name = GetProcAddress(core, #name);                  \
        if (!name) { fprintf(stderr, "missing symbol %s\n", #name); return 2; } \
    } while (0)

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: %s <core.dll> <rom>\n", argv[0]);
        return 2;
    }

    HMODULE core = LoadLibraryA(argv[1]);
    if (!core) { fprintf(stderr, "cannot load %s (%lu)\n", argv[1], GetLastError()); return 2; }

    void (*retro_set_environment)(env_t);
    void (*retro_set_video_refresh)(void *);
    void (*retro_set_audio_sample)(void *);
    void (*retro_set_audio_sample_batch)(void *);
    void (*retro_set_input_poll)(void *);
    void (*retro_set_input_state)(void *);
    void (*retro_init)(void);
    bool (*retro_load_game)(const struct retro_game_info *);

    SYM(retro_set_environment);
    SYM(retro_set_video_refresh);
    SYM(retro_set_audio_sample);
    SYM(retro_set_audio_sample_batch);
    SYM(retro_set_input_poll);
    SYM(retro_set_input_state);
    SYM(retro_init);
    SYM(retro_load_game);

    retro_set_environment(environ_cb);
    retro_set_video_refresh((void *)video_cb);
    retro_set_audio_sample((void *)audio_cb);
    retro_set_audio_sample_batch((void *)audio_batch_cb);
    retro_set_input_poll((void *)input_poll_cb);
    retro_set_input_state((void *)input_state_cb);

    retro_init();

    /* Load the ROM ourselves: the core needs both a path (it derives the
     * directory the sample bank sits in) and the data. */
    FILE *f = fopen(argv[2], "rb");
    if (!f) { fprintf(stderr, "cannot open rom %s\n", argv[2]); return 2; }
    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    void *buf = malloc(size);
    if (fread(buf, 1, size, f) != (size_t)size) { fprintf(stderr, "short read\n"); return 2; }
    fclose(f);

    struct retro_game_info info = { argv[2], buf, (size_t)size, NULL };

    fprintf(stderr, "loading %s (%ld bytes)...\n", argv[2], size);
    bool ok = retro_load_game(&info);

    /* Only reached if the render hook did not fire */
    fprintf(stderr, "retro_load_game returned %d - render hook did not run\n", ok);
    return ok ? 0 : 1;
}
