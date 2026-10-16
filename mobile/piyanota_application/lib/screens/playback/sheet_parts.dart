import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../state/playback_providers.dart';
import '../../theme/app_theme.dart';
import 'playback_messages.dart';

/// Opens a Playback sheet (Voice Mixer, Speed). A modal sheet, not a route
/// push, so the music keeps playing and the seek bar keeps moving
/// underneath (user decision 2026-10-09; 209 AC7, 210 AC5). Completes
/// with what the sheet pops with, or null when dismissed.
///
/// [enableDrag] false for a sheet that must sometimes refuse to close:
/// a drag-down pops the route directly, past any PopScope.
Future<T?> showPlaybackSheet<T>(
  BuildContext context,
  WidgetBuilder builder, {
  bool enableDrag = true,
}) => showModalBottomSheet<T>(
  context: context,
  enableDrag: enableDrag,
  backgroundColor: Colors.white,
  barrierColor: AppTheme.sheetScrim,
  // Grows past the default half screen at large text sizes; scrolls
  // past the top safe area instead of under it.
  isScrollControlled: true,
  useSafeArea: true,
  shape: const RoundedRectangleBorder(
    borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
  ),
  builder: builder,
);

/// The mockups' frame: cyan handle, bold title, grey subtitle, grey X.
/// Export Audio (PIYA-211) has no subtitle, so it is optional.
class SheetFrame extends StatelessWidget {
  const SheetFrame({
    super.key,
    required this.title,
    this.subtitle,
    required this.children,
    this.canClose = true,
  });

  final String title;
  final String? subtitle;

  /// False disables the X, as Export does while it is saving (AC12).
  final bool canClose;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    return SafeArea(
      top: false,
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(16, 0, 8, 16),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const SizedBox(height: 10),
            Center(
              child: Container(
                width: 50,
                height: 4,
                decoration: BoxDecoration(
                  color: AppTheme.sheetHandle,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
            const SizedBox(height: 10),
            Padding(
              padding: const EdgeInsets.only(left: 10),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const SizedBox(height: 8),
                        Semantics(
                          header: true,
                          child: Text(
                            title,
                            style: textTheme.headlineSmall?.copyWith(
                              fontWeight: FontWeight.w700,
                              color: AppTheme.sheetText,
                            ),
                          ),
                        ),
                        if (subtitle case final subtitle?)
                          Text(
                            subtitle,
                            style: textTheme.bodySmall?.copyWith(
                              color: AppTheme.sheetSubtle,
                            ),
                          ),
                      ],
                    ),
                  ),
                  IconButton(
                    tooltip: PlaybackMessages.close,
                    onPressed: canClose
                        ? () => Navigator.of(context).pop()
                        : null,
                    color: AppTheme.sheetClose,
                    iconSize: 28,
                    icon: const Icon(Icons.close_rounded),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 8),
            ...children,
          ],
        ),
      ),
    );
  }
}

/// The mockups' grey square checkbox, with a 48 dp target. Not Material's
/// [Checkbox]: its unchecked box is an outline only, and the mockup's is a
/// filled grey square (given a darker border for the 3:1 a control's
/// outline needs).
class SheetCheckbox extends StatelessWidget {
  const SheetCheckbox({
    super.key,
    required this.value,
    required this.label,
    required this.onChanged,
  });

  static const double boxSize = 26;

  final bool value;

  /// Read by screen readers; nothing is shown.
  final String label;

  /// Null disables it.
  final ValueChanged<bool>? onChanged;

  @override
  Widget build(BuildContext context) {
    final onChanged = this.onChanged;
    return Semantics(
      container: true,
      label: label,
      checked: value,
      enabled: onChanged != null,
      child: InkResponse(
        onTap: onChanged == null ? null : () => onChanged(!value),
        radius: 24,
        child: SizedBox.square(
          dimension: kMinInteractiveDimension,
          child: Center(
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 120),
              width: boxSize,
              height: boxSize,
              decoration: BoxDecoration(
                color: value ? AppTheme.sheetCheckOn : AppTheme.sheetCheckFill,
                border: Border.all(
                  color: value
                      ? AppTheme.sheetCheckOn
                      : AppTheme.sheetCheckBorder,
                  width: 1.5,
                ),
                borderRadius: BorderRadius.circular(5),
              ),
              child: value
                  ? const Icon(
                      Icons.check_rounded,
                      size: 20,
                      color: Colors.white,
                    )
                  : null,
            ),
          ),
        ),
      ),
    );
  }
}

/// The mockups' slider: left of the thumb white with an indigo outline,
/// right of it navy; a white thumb with the same outline.
class SheetSliderTheme extends StatelessWidget {
  const SheetSliderTheme({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) => SliderTheme(
    data: SliderTheme.of(context).copyWith(
      trackHeight: 5,
      trackShape: const _OutlinedTrackShape(),
      thumbShape: const _RingThumbShape(),
      overlayColor: AppTheme.sliderOutline.withValues(alpha: 0.12),
      overlayShape: const RoundSliderOverlayShape(overlayRadius: 18),
      tickMarkShape: SliderTickMarkShape.noTickMark,
      showValueIndicator: ShowValueIndicator.never,
    ),
    child: child,
  );
}

class _OutlinedTrackShape extends SliderTrackShape with BaseSliderTrackShape {
  const _OutlinedTrackShape();

  @override
  void paint(
    PaintingContext context,
    Offset offset, {
    required RenderBox parentBox,
    required SliderThemeData sliderTheme,
    required Animation<double> enableAnimation,
    required TextDirection textDirection,
    required Offset thumbCenter,
    Offset? secondaryOffset,
    bool isDiscrete = false,
    bool isEnabled = false,
    double additionalActiveTrackHeight = 0,
  }) {
    final rect = getPreferredRect(
      parentBox: parentBox,
      offset: offset,
      sliderTheme: sliderTheme,
      isEnabled: isEnabled,
      isDiscrete: isDiscrete,
    );
    final radius = Radius.circular(rect.height / 2);
    final canvas = context.canvas;
    final ltr = textDirection == TextDirection.ltr;
    final split = thumbCenter.dx.clamp(rect.left, rect.right);
    final active = ltr
        ? Rect.fromLTRB(rect.left, rect.top, split, rect.bottom)
        : Rect.fromLTRB(split, rect.top, rect.right, rect.bottom);
    final inactive = ltr
        ? Rect.fromLTRB(split, rect.top, rect.right, rect.bottom)
        : Rect.fromLTRB(rect.left, rect.top, split, rect.bottom);
    canvas
      ..drawRRect(
        RRect.fromRectAndRadius(inactive, radius),
        Paint()..color = AppTheme.sliderInactive,
      )
      ..drawRRect(
        RRect.fromRectAndRadius(active, radius),
        Paint()..color = Colors.white,
      )
      ..drawRRect(
        RRect.fromRectAndRadius(active.deflate(0.5), radius),
        Paint()
          ..color = AppTheme.sliderOutline
          ..style = PaintingStyle.stroke,
      );
  }
}

class _RingThumbShape extends SliderComponentShape {
  const _RingThumbShape();

  static const double radius = 7;

  @override
  Size getPreferredSize(bool isEnabled, bool isDiscrete) =>
      const Size.fromRadius(radius);

  @override
  void paint(
    PaintingContext context,
    Offset center, {
    required Animation<double> activationAnimation,
    required Animation<double> enableAnimation,
    required bool isDiscrete,
    required TextPainter labelPainter,
    required RenderBox parentBox,
    required SliderThemeData sliderTheme,
    required TextDirection textDirection,
    required double value,
    required double textScaleFactor,
    required Size sizeWithOverflow,
  }) {
    context.canvas
      ..drawCircle(center, radius, Paint()..color = Colors.white)
      ..drawCircle(
        center,
        radius - 0.75,
        Paint()
          ..color = AppTheme.sliderOutline
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1.5,
      );
  }
}

/// The mockups' small speaker: with an × (quiet end of a volume slider)
/// or with sound waves (loud end). Decorative; the slider is labelled.
class SpeakerGlyph extends StatelessWidget {
  const SpeakerGlyph({super.key, required this.muted});

  final bool muted;

  @override
  Widget build(BuildContext context) => ExcludeSemantics(
    child: CustomPaint(
      size: const Size(18, 16),
      painter: _SpeakerPainter(muted: muted),
    ),
  );
}

class _SpeakerPainter extends CustomPainter {
  const _SpeakerPainter({required this.muted});

  final bool muted;

  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width;
    final h = size.height;
    final fill = Paint()..color = AppTheme.mixerSpeaker;
    final stroke = Paint()
      ..color = AppTheme.mixerSpeaker
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.4
      ..strokeCap = StrokeCap.round;
    canvas.drawPath(
      Path()
        ..moveTo(0, h * 0.34)
        ..lineTo(w * 0.2, h * 0.34)
        ..lineTo(w * 0.48, h * 0.08)
        ..lineTo(w * 0.48, h * 0.92)
        ..lineTo(w * 0.2, h * 0.66)
        ..lineTo(0, h * 0.66)
        ..close(),
      fill,
    );
    if (muted) {
      canvas
        ..drawLine(
          Offset(w * 0.62, h * 0.36),
          Offset(w * 0.9, h * 0.64),
          stroke,
        )
        ..drawLine(
          Offset(w * 0.9, h * 0.36),
          Offset(w * 0.62, h * 0.64),
          stroke,
        );
      return;
    }
    for (final r in [h * 0.22, h * 0.4]) {
      canvas.drawArc(
        Rect.fromCircle(center: Offset(w * 0.5, h / 2), radius: r),
        -math.pi / 3,
        2 * math.pi / 3,
        false,
        stroke,
      );
    }
  }

  @override
  bool shouldRepaint(_SpeakerPainter oldDelegate) => oldDelegate.muted != muted;
}

/// The mockups' coloured voice label: white text on a rounded pill
/// (Voice Mixer rows, Export rows).
class SheetPill extends StatelessWidget {
  const SheetPill({super.key, required this.label, required this.color});

  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 1),
    decoration: BoxDecoration(
      color: color,
      borderRadius: BorderRadius.circular(10),
    ),
    child: Text(
      label,
      style: Theme.of(context).textTheme.titleMedium
          ?.copyWith(color: Colors.white, fontWeight: FontWeight.w500),
    ),
  );
}

/// A short grey note under a control that can't be used right now.
class SheetNote extends StatelessWidget {
  const SheetNote(this.text, {super.key});

  final String text;

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.fromLTRB(10, 0, 8, 8),
    child: Text(
      text,
      style: Theme.of(context).textTheme.bodySmall
          ?.copyWith(color: AppTheme.sheetSubtle),
    ),
  );
}

/// Whether a sheet row should stack its label above its slider: at large
/// text sizes or on narrow phones the one-line mockup layout leaves the
/// slider too short to use (NFR-10).
bool stackSheetRows(BuildContext context, double width) =>
    width < 360 || MediaQuery.textScalerOf(context).scale(16) > 18.5;

/// A sheet stays open only over a playable score: if the audio fails
/// outright while it is open, it closes onto Playback's error view.
void closeSheetWhenNotReady(BuildContext context, WidgetRef ref, int scoreId) {
  ref.listen(playbackControllerProvider(scoreId).select((s) => s.phase), (
    _,
    phase,
  ) {
    if (phase != PlaybackPhase.ready) Navigator.of(context).maybePop();
  });
}
