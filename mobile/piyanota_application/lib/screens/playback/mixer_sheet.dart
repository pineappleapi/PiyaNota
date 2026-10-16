import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/voice_part.dart';
import '../../state/playback_providers.dart';
import '../../theme/app_theme.dart';
import '../retake/rephotograph.dart';
import 'playback_alerts.dart';
import 'playback_messages.dart';
import 'sheet_parts.dart';

/// Voice Mixer (PIYA-209): per row a Solo checkbox, the voice (or the
/// Metronome Click), a volume slider and a Mute pill. Reads and writes the
/// Playback controller, so its settings last for the Playback session and
/// reset when the score is reopened (AC6).
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
    // Toggle off: the row still takes level, Mute and Solo (they apply
    // once it is on), but looks inactive and says where to turn it on.
    final clickOff = clickUsable && !state.metronomeOn;
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
            soloed: state.soloed.contains(voice),
            muted: state.muted.contains(voice),
            volume: state.volumes[voice] ?? PlaybackController.fullVolume,
            onSolo: (on) => _solo(context, ref, scoreId, voice, soloed: on),
            onMute: (on) => controller.setVoiceMuted(voice, muted: on),
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
          style: Theme.of(context).textTheme.bodyMedium?.copyWith(
            color: clickOff ? AppTheme.sheetSubtle : AppTheme.sheetText,
          ),
        ),
        enabled: clickUsable,
        inactive: clickOff,
        disabledNote: unavailableNote,
        soloed: state.clickSoloed,
        muted: state.clickMuted,
        volume: state.clickVolume,
        onSolo: (on) => controller.setClickSoloed(soloed: on),
        onMute: (on) => controller.setClickMuted(muted: on),
        onVolume: controller.setClickVolume,
      ),
    );
    if (!clickUsable) {
      rows.add(SheetNote(unavailableNote));
    } else if (clickOff) {
      rows.add(
        const SheetNote(
          PlaybackMessages.metronomeOff,
          key: ValueKey('mixer-metronome-off'),
        ),
      );
    }
    return SheetFrame(
      key: const ValueKey('mixer-sheet'),
      title: PlaybackMessages.mixerTitle,
      subtitle: PlaybackMessages.mixerSubtitle,
      children: rows,
    );
  }
}

/// Solo on a voice whose Playback chip is off would be silent, so it asks
/// first (PIYA-209, user decision 2026-10-09: a system alert, not just a
/// hint). "Turn `<Voice>` on" turns the chip on and solos; Cancel leaves
/// both as they were.
Future<void> _solo(
  BuildContext context,
  WidgetRef ref,
  int scoreId,
  VoicePart voice, {
  required bool soloed,
}) async {
  final provider = playbackControllerProvider(scoreId);
  final controller = ref.read(provider.notifier);
  if (!soloed || ref.read(provider).selected.contains(voice)) {
    controller.setVoiceSoloed(voice, soloed: soloed);
    return;
  }
  final turnOn = await showSoloChipOffAlert(context, voice: voice);
  if (!turnOn || !context.mounted) return;
  // The sheet may have closed, or the voice failed, while it was open.
  final state = ref.read(provider);
  if (!state.available.contains(voice)) return;
  if (!state.selected.contains(voice)) controller.toggleVoice(voice);
  controller.setVoiceSoloed(voice, soloed: true);
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
    required this.soloed,
    required this.muted,
    required this.volume,
    required this.onSolo,
    required this.onMute,
    required this.onVolume,
    this.inactive = false,
    this.onDisabledTap,
  });

  /// What a tap on the row does while it is disabled; null for nothing.
  final VoidCallback? onDisabledTap;

  /// The row's name for screen readers ("Soprano", "Metronome Click").
  final String name;
  final Widget label;
  final bool enabled;
  final String disabledNote;
  final bool soloed;
  final bool muted;
  final double volume;
  final ValueChanged<bool> onSolo;
  final ValueChanged<bool> onMute;
  final ValueChanged<double> onVolume;

  /// Usable, but not sounding for now (the metronome with the Speed toggle
  /// off): the slider is drawn faded. Text keeps AA contrast.
  final bool inactive;

  /// Fixed so every row's slider starts at the same x, as in the mockup.
  static const double labelWidth = 112;

  @override
  Widget build(BuildContext context) {
    final solo = SheetCheckbox(
      value: soloed,
      label: PlaybackMessages.soloLabel(name),
      onChanged: enabled ? onSolo : null,
    );
    final slider = Opacity(
      key: const ValueKey('mixer-slider-fade'),
      opacity: inactive ? 0.45 : 1,
      child: Row(
        children: [
          const SpeakerGlyph(muted: true),
          Expanded(
            // Merged so the slider node carries the row's name.
            child: MergeSemantics(
              child: Semantics(
                label: PlaybackMessages.volumeLabel(name),
                child: SheetSliderTheme(
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
          const SpeakerGlyph(muted: false),
        ],
      ),
    );
    final mute = _MutePill(
      muted: muted,
      label: PlaybackMessages.muteLabel(name),
      onChanged: enabled ? onMute : null,
    );
    final row = LayoutBuilder(
      builder: (context, constraints) {
        if (stackSheetRows(context, constraints.maxWidth)) {
          return Column(
            children: [
              Row(
                children: [
                  solo,
                  Expanded(
                    child: Align(alignment: Alignment.centerLeft, child: label),
                  ),
                  mute,
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
            solo,
            SizedBox(
              width: labelWidth,
              child: Align(alignment: Alignment.centerLeft, child: label),
            ),
            Expanded(child: slider),
            mute,
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

/// "Mute": light blue when off, red when on. A toggle, with a 48 dp target
/// around the small pill.
class _MutePill extends StatelessWidget {
  const _MutePill({
    required this.muted,
    required this.label,
    required this.onChanged,
  });

  final bool muted;
  final String label;
  final ValueChanged<bool>? onChanged;

  @override
  Widget build(BuildContext context) {
    final onChanged = this.onChanged;
    return Semantics(
      container: true,
      button: true,
      toggled: muted,
      enabled: onChanged != null,
      label: label,
      excludeSemantics: true,
      child: InkResponse(
        onTap: onChanged == null ? null : () => onChanged(!muted),
        radius: 28,
        child: ConstrainedBox(
          constraints: const BoxConstraints(
            minWidth: 60,
            minHeight: kMinInteractiveDimension,
          ),
          child: Center(
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 120),
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
              decoration: BoxDecoration(
                color: muted ? AppTheme.mixerMuteOn : AppTheme.mixerMuteFill,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                PlaybackMessages.mute,
                style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                  color: muted ? Colors.white : AppTheme.mixerMuteText,
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
