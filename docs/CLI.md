# Command line guide

Everything the web app does can also be done from the command line with `animate.py`. This page is the full reference.

## Setup (Mac)

    brew install ffmpeg
    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt

iPhone HEIC photos work directly. `pillow-heif` is used if installed, and there is a built-in ffmpeg fallback if not.

## Quick start

1. Print a template from `templates/` on A4 at 100% scale (turn off "fit to page"), picking the one that suits the character:
   - `template_hero.pdf`: a sturdy all-rounder, good for most characters, robots and costumes.
   - `template_huggable.pdf`: a big round body with a small head and stubby limbs (marshmallow robots, blob monsters).
   - `template_dancer.pdf`: a slim figure with long arms and long legs (ballerinas, skaters, tall characters).
   Kids colour inside the grey outline with pencils or markers. Anything left undrawn is transparent, so a slim drawing
   on a bigger template is fine. The template is detected from the four corner markers, so you can mix sheets freely.
   Sheets from the very first narrow template (`templates/template_original.pdf`) still work too.
2. Photograph the sheet flat with all four black corner squares in the shot.
3. Make a video:

       python3 animate.py kid.heic --background samples/dancefloor.jpg --out out/dance.mp4

A 16 second video can take a minute or two to render. To check movement quickly without rendering, make a picture sheet of
a few moments instead:

    python3 animate.py kid.heic --background samples/dancefloor.jpg --contact-sheet out/check.png

## Command cheat sheet

    # one drawing
    python3 animate.py kid.heic --out out/dance.mp4                                  # white background
    python3 animate.py kid.heic --background floor.jpg --out out/dance.mp4           # in front of a still image
    python3 animate.py kid.heic --background floor.jpg --travel 0                    # dance on the spot, no walking
    python3 animate.py kid.heic --background floor.jpg --choreo march                # just the original arm swing

    # several drawings (list them in the order you want)
    python3 animate.py a.heic b.heic c.heic --background floor.jpg                   # unison chorus line (default)
    python3 animate.py a.heic b.heic --mode mirror --background floor.jpg            # mirror-image pairs
    python3 animate.py a.heic b.heic --mode conga --background floor.jpg             # follow the leader

    # music
    python3 animate.py kid.heic --background floor.jpg                               # built-in synthesized beat, 120 bpm
    python3 animate.py kid.heic --background floor.jpg --music song.mp3 --bpm 118    # your own track
    python3 animate.py kid.heic --background floor.jpg --music none                  # silent
    python3 -m animator.music 118 20 out/track.wav                                   # just make a beat (bpm, seconds, file)

    # checking and tweaking
    python3 animate.py kid.heic --save-cutouts out/cutouts                           # also save the transparent PNG cut-out
    python3 animate.py kid.heic --contact-sheet out/check.png --sheet-times 0.5,3.7,7  # frames at these seconds, no video
    python3 animate.py kid.heic --seconds 4 --size 640x360                           # quick, small test render
    python3 tools/moves_sheet.py kid.heic out/moves.png                              # every dance move on one sheet
    python3 tools/bench.py                                                           # time a test render (to compare machines)

    # templates and test material
    python3 -m animator.template                                                     # regenerate all printable templates in templates/
    python3 -m animator.template dancer                                              # just one (hero, huggable, dancer, original)
    python3 tools/simulate_drawing.py                                                # fake drawings and photos in samples/

## Several drawings

- **unison** (default): a chorus line. Everyone does the same move on the same beat, walks together and turns together.
  Two drawings stand side by side. Three or more alternate between a front row and a slightly smaller back row so
  neighbours can stand close. The dancers shrink automatically so the group fits and still has room to walk.
- **mirror**: drawings pair up in the order you list them (1st+2nd, 3rd+4th, and so on). The 1st is on the left and the
  2nd is its exact mirror image on the right. They walk towards each other, turn together, walk apart, turn. Extra pairs
  dance in the same phase, nested slightly further out and behind. With an odd number, the last drawing dances on the
  centre line at the back.
- **conga**: follow the leader. Each drawing is `--follow-delay` seconds behind the one in front, rounded to whole beats
  (default 2 beats), repeating the leader's moves and path.

Each dancer is placed by the lowest point of their actual drawing (not the bottom of the template), so a character who
only coloured down to the knees still has their feet on the floor. Size stays true to the template, so shorter
drawings are shorter dancers.

`--char-height` sets a fixed size. The default is 0.74 of the frame height for one drawing and smaller for groups.

## Choreography

The routine lives in `animator/choreo.py`. The legs always do a beat-locked march (a foot lands on every beat). Each move
only controls the upper body: arms, lean, head, a little sideways shift or hop, and optionally a spin.

| Move | What it looks like |
|---|---|
| `swing_across` | Both arms sweep from side to side across the body, hitting each side on a beat |
| `wave` | One hand up, waving every beat, other hand on the hip (`side` is `R` or `L`) |
| `point` | Disco point, one arm sweeping high to low, other hand on the hip (`side` is `R` or `L`) |
| `pump` | Raise the roof: both arms up, hands pumping, body bouncing |
| `clap_over` | Arms open and meet above the head on every beat |
| `shimmy` | Hips sway side to side, hands low and loose |
| `twirl` | A full spin in place over two beats, arms up |
| `arms_out` | Plain T-pose arms, used on the turn-around beat so the spin reads cleanly |
| `march` | The original opposite-to-the-legs arm swing |

`ROUTINE` is a list of `(move, beats, options)`. It loops: the default is 32 beats, which is 16 seconds at 120 bpm.
One crossing of the floor is 8 beats, and the last beat of each crossing is the turn-around. Moves blend into each
other over half a beat.

To add a move, write a function that returns `Upper(...)`, add it to `MOVES`, then use it in `ROUTINE`. Arm angles use a
mirrored "up" convention so both arms read the same way: `up` of 0 is straight out sideways, +90 is straight up, -90 hangs
down, and beyond that swings across the front of the body. `bend` bends the forearm (+ lifts the hand). Other fields:
`torso`, `head`, `dx`, `dy`, `flip` (a spin) and `arms_front` (draw the arms over the torso). Look at `swing_across` or
`wave` for examples, then run `tools/moves_sheet.py` to see the result.

## Music

- The built-in beat is an original synthesized disco loop at `--bpm` (default 120).
- Your own track: `--music song.mp3 --bpm 118`. The dance is retimed to the bpm you give, but the song is not analysed,
  so the first beat of the track should land at the start (or use `--music-offset SECONDS` to skip ahead to it) and the
  tempo should be steady.
- Timing: one step per beat, one full left-and-right cycle every 2 beats, one crossing of the floor every 8 beats.

## Options reference

| Option | Default | What it does |
|---|---|---|
| `photos` | | One or more photos of filled-in sheets (JPEG, PNG or HEIC) |
| `--out` | `out/dance.mp4` | Output video |
| `--seconds` | 16 | Length of the video |
| `--fps` | 24 | Frames per second |
| `--size` | `1280x720` | Video size, width x height |
| `--background` | white | Still image to dance in front of |
| `--char-height` | auto | Hair-to-feet height as a fraction of the frame (0.74 for one drawing, smaller for groups) |
| `--feet-y` | 0.94 | Where the feet land, as a fraction of frame height |
| `--bg-anchor` | 0.7 | Share of any vertical background crop taken off the top (0 to 1) |
| `--mode` | `unison` | Several drawings: `unison`, `mirror` or `conga` |
| `--follow-delay` | 2 beats | Conga only: seconds between dancers, rounded to whole beats |
| `--stagger` | 0 | Phase offset between dancers' steps (0 = all in step) |
| `--choreo` | `dance` | `dance` = the routine in `choreo.py`, `march` = just the original arm swing |
| `--travel` | 0.6 | Fraction of the frame width walked across, back and forth. 0 = dance on the spot |
| `--leg-seconds` | 8 beats | Seconds per crossing, including the turn |
| `--turn-seconds` | 1 beat | Seconds spent turning round at each end |
| `--turn` | `squash` | `squash` = paper-puppet flip at each end, `none` = just reverse direction |
| `--lean` | 4 | Degrees of lean into the direction of travel |
| `--bpm` | 120 | Tempo of the dance and the built-in music |
| `--music` | `auto` | `auto` (built-in beat), `none`, or a path to an audio file |
| `--music-offset` | 0 | Seconds of your audio file to skip |
| `--workers` | cores - 1 | Processes drawing frames in parallel (use 1 if memory is tight) |
| `--save-cutouts` | | Folder to also save each transparent PNG cut-out in |
| `--contact-sheet` | | Write a grid of frames to this PNG and stop, with no video |
| `--sheet-times` | | Seconds of the frames used for `--contact-sheet` (comma separated) |

## Getting good photos

- Lay the sheet flat in even light. Avoid shadows across the page, especially over the four corner squares.
- All four black corner squares must be fully in the photo and not covered by hands. If one is missing the script says which.
- Strong colours work best. Pencil and pastel colours work too. Very faint pencil can be missed.
- Colouring outside the grey outline is fine (hair spikes, hats, a cape), up to about 1 cm beyond it on the page.
- Outlines with a big gap can make an uncoloured area inside the figure turn transparent. Small gaps are bridged automatically.

## Known limits and ideas

- The spin is a flat paper-puppet flip (she goes edge-on for a moment), not a true 3D turn.
- The song is not beat-detected, so your own track needs a steady tempo and a first beat at the start.
- The figure is always the arms-out template: arms and legs bend at the elbow, knee and shoulder, but nothing else.
- One background image per video, and only the dancers move.
- Not built yet: putting the characters into clips from existing videos (the cut-outs already have clean transparency),
  solo moments for individual dancers, and different dance styles per drawing.
