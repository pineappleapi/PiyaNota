import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/voice_part.dart';
import '../../state/playback_providers.dart';
import '../../theme/app_theme.dart';
import 'playback_messages.dart';
import 'sheet_parts.dart';

/// Voice Mixer (PIYA-209): per row a Solo checkbox, the voice (or the
/// Metronome Click), a volume slider and a Mute pill. Reads and writes the
/// Playback controller, so its settings last for the Playback session and
/// reset when the score is reopened (AC6).
class VoiceMixerSheet extends ConsumerWidget {
  const VoiceMixerSheet({super.key, required this.scoreId});

  final int scoreId;

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
    final rows = <Widget>[];
    for (final voice in VoicePart.values) {
      // A voice the result never had has no row; one that failed keeps
      // its row, disabled (partial failure, user decision 2026-10-09).
      if (!(state.result?.audioTracks.containsKey(voice) ?? false)) continue;
      final usable = state.available.contains(voice);
      rows
        ..add(
          _MixerRow(
            key: ValueKey('mixer-row-${voice.name}'),
            name: voice.label,
            label: _VoicePill(voice: voice),
            enabled: usable,
            disabledNote: PlaybackMessages.rowUnavailable(voice.label),
            soloed: state.soloed.contains(voice),
            muted: state.muted.contains(voice),
            volume: state.volumes[voice] ?? PlaybackController.fullVolume,
            onSolo: (on) => controller.setVoiceSoloed(voice, soloed: on),
            onMute: (on) => controller.setVoiceMuted(voice, muted: on),
            onVolume: (level) => controller.setVoiceVolume(voice, level),
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
          style: Theme.of(context).textTheme.bodyMedium
              ?.copyWith(color: AppTheme.sheetText),
        ),
        enabled: clickUsable,
        disabledNote: PlaybackMessages.metronomeUnavailable,
        soloed: state.clickSoloed,
        muted: state.clickMuted,
        volume: state.clickVolume,
        onSolo: (on) => controller.setClickSoloed(soloed: on),
        onMute: (on) => controller.setClickMuted(muted: on),
        onVolume: controller.setClickVolume,
      ),
    );
    if (!clickUsable) {
      rows.add(const SheetNote(PlaybackMessages.metronomeUnavailable));
    }
    return SheetFrame(
      key: const ValueKey('mixer-sheet'),
      title: PlaybackMessages.mixerTitle,
      subtitle: PlaybackMessages.mixerSubtitle,
      children: rows,
    );
  }
}

class _VoicePill extends StatelessWidget {
  const _VoicePill({required this.voice});

  final VoicePart voice;

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 1),
    decoration: BoxDecoration(
      color: VoiceMixerSheet.pillColors[voice],
      borderRadius: BorderRadius.circular(10),
    ),
    child: Text(
      voice.label,
      style: Theme.of(context).textTheme.titleMedium
          ?.copyWith(color: Colors.white, fontWeight: FontWeight.w500),
    ),
  );
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
  });

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

  /// Fixed so every row's slider starts at the same x, as in the mockup.
  static const double labelWidth = 112;

  @override
  Widget build(BuildContext context) {
    final solo = SheetCheckbox(
      value: soloed,
      label: PlaybackMessages.soloLabel(name),
      onChanged: enabled ? onSolo : null,
    );
    final slider = Row(
      children: [
        const SpeakerGlyph(muted: true),
        Expanded(
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
        const SpeakerGlyph(muted: false),
      ],
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
    return Semantics(
      container: true,
      label: disabledNote,
      child: Opacity(opacity: 0.38, child: row),
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
