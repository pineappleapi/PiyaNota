import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/score_details.dart';
import '../../state/playback_providers.dart';
import '../../theme/app_theme.dart';
import 'playback_messages.dart';
import 'sheet_parts.dart';

/// Playback Speed (PIYA-210): the Metronome Click on/off toggle and a BPM
/// slider. The slider is in BPM (30-240) and opens at the score's
/// `tempoBpm`; the audio plays at rate = BPM / tempoBpm through the
/// engine's pitch-preserving speed (FR-9, PIYA-103 AC8). State lives in the
/// Playback controller, so it lasts for the session and resets on reopen.
class PlaybackSpeedSheet extends ConsumerWidget {
  const PlaybackSpeedSheet({super.key, required this.scoreId});

  final int scoreId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    closeSheetWhenNotReady(context, ref, scoreId);
    final provider = playbackControllerProvider(scoreId);
    final state = ref.watch(provider);
    final controller = ref.read(provider.notifier);
    final textTheme = Theme.of(context).textTheme;
    final clickUsable = state.clickStatus != ClickStatus.unavailable;
    final bpm = state.chosenBpm;

    final metronome = Row(
      key: const ValueKey('speed-metronome-row'),
      children: [
        const Padding(
          padding: EdgeInsets.symmetric(horizontal: 10),
          child: ExcludeSemantics(
            child: CustomPaint(
              size: Size(26, 30),
              painter: _FilledMetronomePainter(),
            ),
          ),
        ),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                PlaybackMessages.metronomeClick,
                style: textTheme.titleMedium?.copyWith(
                  color: AppTheme.sheetText,
                  fontWeight: FontWeight.w600,
                ),
              ),
              Text(
                PlaybackMessages.metronomeHint,
                style: textTheme.bodySmall?.copyWith(
                  color: AppTheme.sheetSubtle,
                ),
              ),
            ],
          ),
        ),
        SheetCheckbox(
          key: const ValueKey('metronome-toggle'),
          value: state.metronomeOn,
          label: PlaybackMessages.metronomeClick,
          // Independent of the mixer's metronome Mute (210 AC3).
          onChanged: clickUsable
              ? (on) => controller.setMetronomeOn(on: on)
              : null,
        ),
      ],
    );

    return SheetFrame(
      key: const ValueKey('speed-sheet'),
      title: PlaybackMessages.speedTitle,
      subtitle: PlaybackMessages.speedSubtitle,
      children: [
        const SizedBox(height: 8),
        if (clickUsable)
          metronome
        else
          Semantics(
            container: true,
            label: PlaybackMessages.metronomeUnavailable,
            child: Opacity(opacity: 0.38, child: metronome),
          ),
        if (!clickUsable)
          const SheetNote(PlaybackMessages.metronomeUnavailable),
        const SizedBox(height: 8),
        const Divider(height: 1, color: AppTheme.sheetDivider),
        const SizedBox(height: 12),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 10),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  PlaybackMessages.playbackSpeed,
                  style: textTheme.titleMedium?.copyWith(
                    color: AppTheme.sheetText,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              ExcludeSemantics(
                child: Text(
                  PlaybackMessages.bpmValue(bpm),
                  key: const ValueKey('speed-bpm'),
                  style: textTheme.titleMedium?.copyWith(
                    color: AppTheme.sheetText,
                  ),
                ),
              ),
            ],
          ),
        ),
        // Merged so the slider node itself carries the name; a plain
        // Semantics parent leaves TalkBack reading the value unnamed.
        MergeSemantics(
          child: Semantics(
            label: PlaybackMessages.playbackSpeed,
            child: SheetSliderTheme(
              child: Slider(
                key: const ValueKey('speed-slider'),
                value: bpm.toDouble(),
                min: ScoreDetails.minTempo.toDouble(),
                max: ScoreDetails.maxTempo.toDouble(),
                divisions: ScoreDetails.maxTempo - ScoreDetails.minTempo,
                semanticFormatterCallback: (v) =>
                    PlaybackMessages.bpmSpoken(v.round()),
                // On every change, so a drag is heard as it moves (210 AC4).
                onChanged: (v) => controller.setBpm(v.round()),
              ),
            ),
          ),
        ),
      ],
    );
  }
}

/// The mockup's solid blue metronome, white pendulum.
class _FilledMetronomePainter extends CustomPainter {
  const _FilledMetronomePainter();

  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width;
    final h = size.height;
    final body = Path()
      ..moveTo(w * 0.38, h * 0.04)
      ..lineTo(w * 0.62, h * 0.04)
      ..lineTo(w * 0.92, h * 0.96)
      ..lineTo(w * 0.08, h * 0.96)
      ..close();
    final white = Paint()
      ..color = Colors.white
      ..strokeWidth = w * 0.09
      ..strokeCap = StrokeCap.round;
    canvas
      ..drawPath(body, Paint()..color = AppTheme.speedMetronome)
      ..drawLine(Offset(w * 0.5, h * 0.78), Offset(w * 0.72, h * 0.24), white)
      ..drawCircle(Offset(w * 0.63, h * 0.46), w * 0.08, white)
      ..drawLine(
        Offset(w * 0.2, h * 0.8),
        Offset(w * 0.8, h * 0.8),
        Paint()
          ..color = Colors.white
          ..strokeWidth = w * 0.07,
      );
  }

  @override
  bool shouldRepaint(_FilledMetronomePainter oldDelegate) => false;
}
