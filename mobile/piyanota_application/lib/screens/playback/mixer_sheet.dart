import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/voice_part.dart';
import '../../state/playback_providers.dart';
import '../../theme/app_theme.dart';
import '../retake/rephotograph.dart';
import 'playback_messages.dart';
import 'sheet_parts.dart';

/// Voice Mixer (PIYA-209): per row a checkbox, the voice (or the Metronome
/// Click), a volume slider whose end icons jump to 0 / full. A voice's checkbox is the same
/// state as its Playback chip; the Metronome row's is the Speed sheet's. Reads and writes the
/// Playback controller, so its mix and speed persist per score (user
/// decision 2026-11-09, supersedes 209 AC6).
class VoiceMixerSheet extends ConsumerWidget {
  const VoiceMixerSheet({
    super.key,
    required this.scoreId,
    this.onRephotograph,
  });

  final int scoreId;

  /// Starts the whole-score retake (PIYA-209: an `unreadable` row's tap
  /// offers it). Called after the sheet has closed.
  final VoidCallback? onRephotograph;

  static const Map<VoicePart, Color> pillColors = {
    VoicePart.soprano: AppTheme.mixerSoprano,
    VoicePart.alto: AppTheme.mixerAlto,
    VoicePart.tenor: AppTheme.mixerTenor,
    VoicePart.bass: AppTheme.mixerBass,
  };

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    closeSheetWhenNotReady(context, ref, scoreId);
    final provider = playbackControllerProvider(scoreId);
    final state = ref.watch(provider);
    final controller = ref.read(provider.notifier);
    final clickUsable = state.clickStatus != ClickStatus.unavailable;
    final unavailableNote = state.clickNeedsTempo
        ? PlaybackMessages.metronomeNeedsTempo
        : PlaybackMessages.metronomeUnavailable;
    final rows = <Widget>[];
    for (final voice in VoicePart.values) {
      // Every voice keeps its row; one that can't play (failed on the
      // server or on the device) is disabled (user decision 2026-10-09).
      final usable = state.available.contains(voice);
      // PIYA-209: an `unreadable` row offers the whole-score retake; a
      // `render_failed` (or device-failed) row offers nothing.
      final unreadable =
          !usable &&
          onRephotograph != null &&
          (state.result?.unreadableVoices.contains(voice) ?? false);
      rows
        ..add(
          _MixerRow(
            key: ValueKey('mixer-row-${voice.name}'),
            name: voice.label,
            label: SheetPill(label: voice.label, color: pillColors[voice]!),
            enabled: usable,
            disabledNote: PlaybackMessages.rowUnavailable(voice.label),
            checked: state.selected.contains(voice),
            muted: state.muted.contains(voice),
            volume:
                state.volumes[voice] ?? PlaybackController.defaultVoiceVolume,
            onChecked: (_) => controller.toggleVoice(voice),
            onVolume: (level) => controller.setVoiceVolume(voice, level),
            onDisabledTap: unreadable
                ? () => _offerRetake(context, voice)
                : null,
          ),
        )
        ..add(const Divider(height: 1, color: AppTheme.sheetDivider));
    }
    rows.add(
      _MixerRow(
        key: const ValueKey('mixer-row-metronome'),
        name: PlaybackMessages.metronomeClick,
        label: Text(
          PlaybackMessages.metronomeClick,
          // Same style on or off (PIYA-209-V2.1).
          style: Theme.of(context).textTheme.bodyMedium
              ?.copyWith(color: AppTheme.sheetText),
        ),
        enabled: clickUsable,
        disabledNote: unavailableNote,
        checked: state.metronomeOn,
        muted: state.clickMuted,
        volume: state.clickVolume,
        onChecked: (on) => controller.setMetronomeOn(on: on),
        onVolume: controller.setClickVolume,
      ),
    );
    if (!clickUsable) {
      rows.add(SheetNote(unavailableNote));
    }
    return SheetFrame(
      key: const ValueKey('mixer-sheet'),
      title: PlaybackMessages.mixerTitle,
      subtitle: PlaybackMessages.mixerSubtitle,
      children: rows,
    );
  }
}

extension on VoiceMixerSheet {
  /// "Re-photograph" closes the Mixer and leaves Playback for Capture
  /// (PIYA-209); Cancel leaves everything as it was.
  Future<void> _offerRetake(BuildContext context, VoicePart voice) async {
    final retake = await showUnreadableVoiceAlert(context, voice: voice);
    if (!retake || !context.mounted) return;
    Navigator.of(context).pop();
    onRephotograph?.call();
  }
}

class _MixerRow extends StatelessWidget {
  const _MixerRow({
    super.key,
    required this.name,
    required this.label,
    required this.enabled,
    required this.disabledNote,
    required this.checked,
    required this.muted,
    required this.volume,
    required this.onChecked,
    required this.onVolume,
    this.onDisabledTap,
  });

  /// What a tap on the row does while it is disabled; null for nothing.
  final VoidCallback? onDisabledTap;

  /// The row's name for screen readers ("Soprano", "Metronome Click").
  final String name;
  final Widget label;
  final bool enabled;
  final String disabledNote;
  final bool checked;
  final bool muted;
  final double volume;
  final ValueChanged<bool> onChecked;
  final ValueChanged<double> onVolume;

  /// Fixed so every row's slider starts at the same x, as in the mockup.
  static const double labelWidth = 112;

  @override
  Widget build(BuildContext context) {
    final check = SheetCheckbox(
      value: checked,
      label: PlaybackMessages.playLabel(name),
      onChanged: enabled ? onChecked : null,
    );
    final slider = Opacity(
      key: const ValueKey('mixer-slider-fade'),
      // A muted row (default mix) is dimmed (PIYA-209-V2.4).
      opacity: muted ? 0.45 : 1,
      child: Row(
        children: [
          _GlyphButton(
            muted: true,
            label: PlaybackMessages.minVolumeLabel(name),
            onTap: enabled ? () => onVolume(0) : null,
          ),
          Expanded(
            // Merged so the slider node carries the row's name.
            child: MergeSemantics(
              child: Semantics(
                label: PlaybackMessages.volumeLabel(name),
                child: SheetSliderTheme(
                  gradientFill: true,
                  child: Slider(
                    // Muting leaves the slider where it was (AC4).
                    value: volume,
                    semanticFormatterCallback: PlaybackMessages.volumeValue,
                    // On every change, not on change-end: AC3's 100 ms.
                    onChanged: enabled ? onVolume : null,
                  ),
                ),
              ),
            ),
          ),
          _GlyphButton(
            muted: false,
            label: PlaybackMessages.maxVolumeLabel(name),
            onTap: enabled ? () => onVolume(1) : null,
          ),
        ],
      ),
    );
    final row = LayoutBuilder(
      builder: (context, constraints) {
        if (stackSheetRows(context, constraints.maxWidth)) {
          return Column(
            children: [
              Row(
                children: [
                  check,
                  Expanded(
                    child: Align(alignment: Alignment.centerLeft, child: label),
                  ),
                ],
              ),
              Padding(
                padding: const EdgeInsets.only(left: kMinInteractiveDimension),
                child: slider,
              ),
            ],
          );
        }
        return Row(
          children: [
            check,
            SizedBox(
              width: labelWidth,
              child: Align(alignment: Alignment.centerLeft, child: label),
            ),
            Expanded(child: slider),
          ],
        );
      },
    );
    if (enabled) return row;
    final faded = Semantics(
      container: true,
      label: disabledNote,
      button: onDisabledTap != null,
      onTap: onDisabledTap,
      child: Opacity(opacity: 0.38, child: row),
    );
    if (onDisabledTap == null) return faded;
    // The row's own controls are disabled, so the whole row takes the tap.
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: onDisabledTap,
      child: faded,
    );
  }
}

/// Speaker icon at a slider end: tap jumps the volume to that end. 48 dp
/// target around the small glyph.
class _GlyphButton extends StatelessWidget {
  const _GlyphButton({
    required this.muted,
    required this.label,
    required this.onTap,
  });

  final bool muted;
  final String label;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) => Semantics(
    container: true,
    button: true,
    enabled: onTap != null,
    label: label,
    excludeSemantics: true,
    child: InkResponse(
      onTap: onTap,
      radius: 24,
      child: ConstrainedBox(
        constraints: const BoxConstraints(
          minWidth: kMinInteractiveDimension,
          minHeight: kMinInteractiveDimension,
        ),
        child: Center(child: SpeakerGlyph(muted: muted)),
      ),
    ),
  );
}
