import 'dart:async';

import 'package:flutter/material.dart';

import '../../services/piano_octave.dart';
import '../../services/piano_octave_store.dart';
import '../../services/piano_sound.dart';
import '../../services/piano_sync_service.dart';
import '../../theme/app_theme.dart';
import 'piano_messages.dart';

const double _kKeyboardHeight = 230;
const double _kBlackKeyWidthRatio = 0.6;
const double _kBlackKeyHeightRatio = 0.62;
const double _kKeyRadius = 8;
const double _kChevronSize = 44;
const double _kDotSize = 10;
const double _kSheetRadius = 28;
const double _kCloseSwipePx = 600;
const Duration _kSlide = Duration(milliseconds: 180);
const List<String> _kWhiteNames = ['C', 'D', 'E', 'F', 'G', 'A', 'B'];
const List<String> _kSuperscripts = ['⁰', '¹', '²', '³', '⁴', '⁵', '⁶', '⁷'];

/// Black keys: [boundary] is the white-key index they sit after, [flat] on
/// top and [sharp] below (AC 6); one key, one pitch (AC 11).
class _BlackKey {
  const _BlackKey(this.boundary, this.semitone, this.flat, this.sharp);
  final int boundary;
  final int semitone;
  final String flat;
  final String sharp;
}

const List<_BlackKey> _kBlackKeys = [
  _BlackKey(1, 1, 'D♭', 'C♯'),
  _BlackKey(2, 3, 'E♭', 'D♯'),
  _BlackKey(4, 6, 'G♭', 'F♯'),
  _BlackKey(5, 8, 'A♭', 'G♯'),
  _BlackKey(6, 10, 'B♭', 'A♯'),
];

/// Opens the piano over the score (PIYA-218). The Notes Chart lives in the
/// same sheet so closing the sheet closes both (AC 34).
Future<void> showPianoModal(
  BuildContext context, {
  required int initialOctave,
  required PianoSound? sound,
  PianoOctaveStore? store,
  PianoSyncService? sync,
}) {
  return showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    enableDrag: false,
    backgroundColor: Colors.transparent,
    elevation: 0,
    builder: (_) => PianoModal(
      initialOctave: initialOctave,
      sound: sound,
      store: store ?? PianoOctaveStore(),
      sync: sync,
    ),
  );
}

class PianoModal extends StatefulWidget {
  const PianoModal({
    super.key,
    required this.initialOctave,
    required this.sound,
    required this.store,
    this.sync,
  });

  final int initialOctave;
  final PianoSound? sound;
  final PianoOctaveStore store;

  /// Server sync (AC 40-48); null keeps the piano purely local.
  final PianoSyncService? sync;

  @override
  State<PianoModal> createState() => _PianoModalState();
}

class _PianoModalState extends State<PianoModal> with WidgetsBindingObserver {
  late int _octave = widget.initialOctave;
  int _direction = 1;
  bool _chartOpen = false;
  bool _soundMissing = false;
  bool _touched = false;

  /// True once the open-time reconcile has finished (or there is none); until
  /// then a close must not stamp a fresh timestamp over an unseen server value.
  late bool _reconciled = widget.sync == null;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _soundMissing = widget.sound == null;
    unawaited(_reconcile());
  }

  /// AC 40-42: already drawn from the local octave; a server value shows
  /// now only if the user hasn't touched the octave, else next open.
  Future<void> _reconcile() async {
    int? adopted;
    try {
      adopted = await widget.sync?.reconcile();
    } finally {
      _reconciled = true;
    }
    final value = adopted;
    if (value == null || _touched || !mounted || value == _octave) return;
    widget.sound?.releaseAll();
    setState(() => _octave = value);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    widget.sound?.releaseAll();
    unawaited(_saveOnClose(_octave));
    super.dispose();
  }

  /// AC 28 + AC 44. A changed octave was already saved by [_step]; an
  /// untouched one is saved only as the first-ever value, and only once
  /// reconcile has run, so a close never re-stamps an existing value or beats
  /// a server value still on its way.
  Future<void> _saveOnClose(int octave) async {
    final sync = widget.sync;
    if (!_touched && _reconciled && await widget.store.loadSaved() == null) {
      await widget.store.save(octave);
      await sync?.flush(force: true);
      return;
    }
    await sync?.flush();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused) unawaited(_flushSync());
    if (state == AppLifecycleState.paused && mounted) {
      Navigator.of(context).maybePop(); // AC 35: chart goes with the sheet.
    }
  }

  Future<void> _flushSync() async => widget.sync?.flush();

  void _step(int delta) {
    final next = _octave + delta;
    if (!isValidOctave(next)) return;
    widget.sound?.releaseAll(); // AC 22
    _touched = true;
    setState(() {
      _direction = delta;
      _octave = next;
    });
    unawaited(
      widget.store.save(next).whenComplete(() => widget.sync?.localChanged()),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisSize: MainAxisSize.min,
      mainAxisAlignment: MainAxisAlignment.end,
      children: [
        if (_chartOpen)
          _NotesChartCard(
            onClose: () => setState(() => _chartOpen = false),
          ),
        _PianoPanel(
          octave: _octave,
          direction: _direction,
          sound: widget.sound,
          soundMissing: _soundMissing,
          onSoundMissing: () {
            if (!_soundMissing) setState(() => _soundMissing = true);
          },
          onLower: _octave > kPianoMinOctave ? () => _step(-1) : null,
          onHigher: _octave < kPianoMaxOctave ? () => _step(1) : null,
          onInfo: () => setState(() => _chartOpen = true), // AC 36: stays open
          onClose: () => Navigator.of(context).maybePop(),
        ),
      ],
    );
  }
}

class _PianoPanel extends StatelessWidget {
  const _PianoPanel({
    required this.octave,
    required this.direction,
    required this.sound,
    required this.soundMissing,
    required this.onSoundMissing,
    required this.onLower,
    required this.onHigher,
    required this.onInfo,
    required this.onClose,
  });

  final int octave;
  final int direction;
  final PianoSound? sound;
  final bool soundMissing;
  final VoidCallback onSoundMissing;
  final VoidCallback? onLower;
  final VoidCallback? onHigher;
  final VoidCallback onInfo;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    return Material(
      color: Colors.white,
      borderRadius: const BorderRadius.vertical(
        top: Radius.circular(_kSheetRadius),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          // Swipe down from the handle area closes (AC 3).
          GestureDetector(
            behavior: HitTestBehavior.opaque,
            onVerticalDragEnd: (d) {
              if ((d.primaryVelocity ?? 0) > _kCloseSwipePx / 4) onClose();
            },
            child: Column(
              children: [
                const SizedBox(height: 10),
                Container(
                  width: 44,
                  height: 4,
                  decoration: BoxDecoration(
                    gradient: const LinearGradient(
                      colors: [AppTheme.gradientStart, AppTheme.gradientEnd],
                    ),
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 12, 8, 4),
                  child: Row(
                    children: [
                      IconButton(
                        tooltip: PianoMessages.info,
                        onPressed: onInfo,
                        icon: const Icon(
                          Icons.info_rounded,
                          color: AppTheme.pianoInfo,
                        ),
                      ),
                      const SizedBox(width: 4),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Semantics(
                              header: true,
                              child: Text(
                                PianoMessages.title,
                                style: textTheme.headlineSmall?.copyWith(
                                  fontWeight: FontWeight.w700,
                                  color: AppTheme.playbackTitle,
                                ),
                              ),
                            ),
                            Text(
                              soundMissing
                                  ? PianoMessages.soundUnavailable
                                  : PianoMessages.description,
                              style: textTheme.bodySmall?.copyWith(
                                color: AppTheme.playbackSubtle,
                              ),
                            ),
                          ],
                        ),
                      ),
                      IconButton(
                        tooltip: PianoMessages.close,
                        onPressed: onClose,
                        icon: const Icon(
                          Icons.close_rounded,
                          color: AppTheme.playbackSubtle,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          _OctaveRow(
            octave: octave,
            onLower: onLower,
            onHigher: onHigher,
          ),
          const SizedBox(height: 12),
          SizedBox(
            height: _kKeyboardHeight,
            child: ClipRect(
              child: AnimatedSwitcher(
                duration: _kSlide,
                transitionBuilder: (child, animation) {
                  final incoming = child.key == ValueKey<int>(octave);
                  final from = Offset(
                    incoming ? direction.toDouble() : -direction.toDouble(),
                    0,
                  );
                  return SlideTransition(
                    position: Tween<Offset>(begin: from, end: Offset.zero)
                        .animate(animation),
                    child: child,
                  );
                },
                child: _Keyboard(
                  key: ValueKey<int>(octave),
                  octave: octave,
                  sound: sound,
                  onSoundMissing: onSoundMissing,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _OctaveRow extends StatelessWidget {
  const _OctaveRow({
    required this.octave,
    required this.onLower,
    required this.onHigher,
  });

  final int octave;
  final VoidCallback? onLower;
  final VoidCallback? onHigher;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _Chevron(
            icon: Icons.chevron_left_rounded,
            caption: PianoMessages.lower,
            a11y: PianoMessages.lowerA11y,
            onPressed: onLower,
          ),
          Expanded(
            child: Column(
              children: [
                const SizedBox(height: 6),
                // Indicator only (AC 23): five dots, octave 2..6 (AC 20).
                Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    for (var o = kPianoMinOctave; o <= kPianoMaxOctave; o++)
                      AnimatedContainer(
                        duration: _kSlide,
                        margin: const EdgeInsets.symmetric(horizontal: 4),
                        width: _kDotSize,
                        height: _kDotSize,
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: o == octave ? null : AppTheme.pianoDotInactive,
                          gradient: o == octave
                              ? const LinearGradient(
                                  colors: [
                                    AppTheme.gradientStart,
                                    AppTheme.gradientEnd,
                                  ],
                                )
                              : null,
                        ),
                      ),
                  ],
                ),
                const SizedBox(height: 6),
                Semantics(
                  liveRegion: true,
                  label: PianoMessages.octave(octave),
                  child: ExcludeSemantics(
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 22,
                        vertical: 3,
                      ),
                      decoration: BoxDecoration(
                        gradient: const LinearGradient(
                          colors: [AppTheme.gradientStart, AppTheme.gradientEnd],
                        ),
                        borderRadius: BorderRadius.circular(6),
                      ),
                      child: Text(
                        PianoMessages.octave(octave),
                        style: textTheme.labelMedium?.copyWith(
                          color: Colors.white,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
          _Chevron(
            icon: Icons.chevron_right_rounded,
            caption: PianoMessages.higher,
            a11y: PianoMessages.higherA11y,
            onPressed: onHigher,
          ),
        ],
      ),
    );
  }
}

class _Chevron extends StatelessWidget {
  const _Chevron({
    required this.icon,
    required this.caption,
    required this.a11y,
    required this.onPressed,
  });

  final IconData icon;
  final String caption;
  final String a11y;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        IconButton.filled(
          tooltip: a11y,
          onPressed: onPressed,
          icon: Icon(icon),
          iconSize: 28,
          style: IconButton.styleFrom(
            backgroundColor: AppTheme.playbackNavy,
            foregroundColor: Colors.white,
            disabledBackgroundColor: AppTheme.pianoChevronDisabled,
            disabledForegroundColor: Colors.white,
            fixedSize: const Size.square(_kChevronSize),
            minimumSize: const Size.square(_kChevronSize),
            padding: EdgeInsets.zero,
          ),
        ),
        ExcludeSemantics(
          child: Text(
            caption,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
              color: AppTheme.playbackSubtle,
            ),
          ),
        ),
      ],
    );
  }
}

/// 7 white + 5 black keys with raw pointer tracking so several keys can be
/// held at once (AC 12). Held notes are released on dispose, which is what an
/// octave change or close does to this widget (AC 22).
class _Keyboard extends StatefulWidget {
  const _Keyboard({
    super.key,
    required this.octave,
    required this.sound,
    required this.onSoundMissing,
  });

  final int octave;
  final PianoSound? sound;
  final VoidCallback onSoundMissing;

  @override
  State<_Keyboard> createState() => _KeyboardState();
}

class _KeyboardState extends State<_Keyboard> {
  final Map<int, int> _held = {}; // pointer -> semitone from C
  double _width = 0;

  int? _semitoneAt(Offset p) {
    final whiteW = _width / 7;
    if (p.dy < _kKeyboardHeight * _kBlackKeyHeightRatio) {
      for (final k in _kBlackKeys) {
        final cx = k.boundary * whiteW;
        if ((p.dx - cx).abs() <= whiteW * _kBlackKeyWidthRatio / 2) {
          return k.semitone;
        }
      }
    }
    final i = (p.dx / whiteW).floor().clamp(0, 6);
    return kWhiteKeyOffsets[i];
  }

  void _down(PointerDownEvent e) => _press(e.pointer, _semitoneAt(e.localPosition));

  void _press(int pointer, int? semitone) {
    if (semitone == null) return;
    final sound = widget.sound;
    if (sound == null) {
      widget.onSoundMissing(); // keys still show pressed (AC 15)
    } else if (!_held.containsValue(semitone)) {
      // A second finger on a held key adds no note-on.
      sound.noteOn(midiForC(widget.octave) + semitone, kPianoNoteVelocity);
    }
    setState(() => _held[pointer] = semitone);
  }

  void _release(int pointer) {
    final semitone = _held[pointer];
    if (semitone == null) return;
    setState(() => _held.remove(pointer));
    // Only the last finger on the key ends the note.
    if (!_held.containsValue(semitone)) {
      widget.sound?.noteOff(midiForC(widget.octave) + semitone);
    }
  }

  void _move(PointerMoveEvent e) {
    final now = _semitoneAt(e.localPosition);
    final was = _held[e.pointer];
    if (was == null || now == was) return;
    _release(e.pointer); // AC 9: leaving the key clears it
    _press(e.pointer, now);
  }

  @override
  void dispose() {
    for (final s in _held.values.toSet()) {
      widget.sound?.noteOff(midiForC(widget.octave) + s);
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final pressed = _held.values.toSet();
    return LayoutBuilder(
      builder: (context, c) {
        _width = c.maxWidth;
        final whiteW = _width / 7;
        return Listener(
          behavior: HitTestBehavior.opaque,
          onPointerDown: _down,
          onPointerMove: _move,
          onPointerUp: (e) => _release(e.pointer),
          onPointerCancel: (e) => _release(e.pointer),
          child: Stack(
            children: [
              Row(
                children: [
                  for (var i = 0; i < 7; i++)
                    _WhiteKey(
                      width: whiteW,
                      name: _kWhiteNames[i],
                      octave: widget.octave,
                      pressed: pressed.contains(kWhiteKeyOffsets[i]),
                    ),
                ],
              ),
              for (final k in _kBlackKeys)
                Positioned(
                  left: k.boundary * whiteW - whiteW * _kBlackKeyWidthRatio / 2,
                  top: 0,
                  width: whiteW * _kBlackKeyWidthRatio,
                  height: _kKeyboardHeight * _kBlackKeyHeightRatio,
                  child: _BlackKeyView(
                    key_: k,
                    octave: widget.octave,
                    pressed: pressed.contains(k.semitone),
                  ),
                ),
            ],
          ),
        );
      },
    );
  }
}

class _WhiteKey extends StatelessWidget {
  const _WhiteKey({
    required this.width,
    required this.name,
    required this.octave,
    required this.pressed,
  });

  final double width;
  final String name;
  final int octave;
  final bool pressed;

  @override
  Widget build(BuildContext context) {
    final isMiddleC = name == 'C' && octave == kPianoMiddleCOctave; // AC 7
    final label = name == 'C' ? 'C${_kSuperscripts[octave]}' : name;
    return Semantics(
      label: PianoMessages.keyA11y(name, octave),
      button: true,
      child: Container(
        width: width,
        decoration: BoxDecoration(
          color: pressed ? AppTheme.pianoWhiteKeyPressed : Colors.white,
          border: Border.all(color: AppTheme.pianoWhiteKeyBorder),
          borderRadius: const BorderRadius.vertical(
            bottom: Radius.circular(_kKeyRadius),
          ),
        ),
        alignment: Alignment.bottomCenter,
        padding: const EdgeInsets.only(bottom: 14),
        child: ExcludeSemantics(
          child: Text(
            label,
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
              fontWeight: FontWeight.w600,
              color: isMiddleC ? AppTheme.pianoMiddleC : AppTheme.pianoLabel,
            ),
          ),
        ),
      ),
    );
  }
}

class _BlackKeyView extends StatelessWidget {
  const _BlackKeyView({
    required this.key_,
    required this.octave,
    required this.pressed,
  });

  final _BlackKey key_;
  final int octave;
  final bool pressed;

  @override
  Widget build(BuildContext context) {
    final style = Theme.of(context).textTheme.bodySmall?.copyWith(
      color: Colors.white,
      height: 1.2,
    );
    return Semantics(
      label: PianoMessages.keyA11y(
        '${key_.sharp.replaceFirst('♯', ' sharp')} or '
        '${key_.flat.replaceFirst('♭', ' flat')}',
        octave,
      ),
      button: true,
      child: Container(
        decoration: BoxDecoration(
          color: pressed ? AppTheme.pianoBlackKeyPressed : AppTheme.pianoBlackKey,
          borderRadius: const BorderRadius.vertical(
            bottom: Radius.circular(_kKeyRadius),
          ),
        ),
        alignment: Alignment.bottomCenter,
        padding: const EdgeInsets.only(bottom: 14),
        child: ExcludeSemantics(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(key_.flat, style: style),
              Text(key_.sharp, style: style),
            ],
          ),
        ),
      ),
    );
  }
}

/// Static Notes Chart (AC 29-31); the image has its own margins plus the
/// card padding, so it never touches the card edge.
class _NotesChartCard extends StatelessWidget {
  const _NotesChartCard({required this.onClose});

  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
      child: Material(
        color: Colors.white,
        borderRadius: BorderRadius.circular(20),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Row(
                children: [
                  const SizedBox(width: 48),
                  Expanded(
                    child: Semantics(
                      header: true,
                      child: Text(
                        PianoMessages.chartTitle,
                        textAlign: TextAlign.center,
                        style: textTheme.titleMedium?.copyWith(
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                  ),
                  IconButton(
                    tooltip: PianoMessages.chartClose,
                    onPressed: onClose,
                    icon: const Icon(
                      Icons.close_rounded,
                      color: AppTheme.playbackSubtle,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 8),
              Semantics(
                image: true,
                label: PianoMessages.chartA11y,
                child: Image.asset(
                  'assets/piano/notes_chart.png',
                  fit: BoxFit.contain,
                  excludeFromSemantics: true,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
