import 'package:flutter/material.dart';

import '../../../models/voice_part.dart';
import '../../../theme/app_theme.dart';
import '../../playback/mixer_sheet.dart';
import '../settings_messages.dart';

/// PIYA-212 AC7 and PIYA-212-V2.1: "All voices" plus the four voices as
/// single-select pills. The voices wear their Voice Mixer colours, so the
/// choice looks like the voice it turns on in Playback; "All voices" belongs
/// to no one voice and uses the chip text colour (white on it 5.9:1). The
/// chosen pill is filled with a white tick; the rest are outlined in their
/// colour. Every mixer colour is 4.5:1 against white either way round (see
/// AppTheme.mixerSoprano), so both states pass AA.
class VoicePicker extends StatelessWidget {
  const VoicePicker({
    super.key,
    required this.selected,
    required this.onChanged,
  });

  /// Null when no voice is saved: "All voices" is then the selected pill.
  final VoicePart? selected;

  /// Null means "All voices" (PIYA-212-V2.1).
  final ValueChanged<VoicePart?> onChanged;

  static const double _gap = 8;

  @override
  Widget build(BuildContext context) {
    // One per line so choosing a voice never moves the others.
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      spacing: _gap,
      children: [
        _VoicePill(
          label: SettingsMessages.allVoices,
          color: AppTheme.playbackChipText,
          selected: selected == null,
          onTap: () => onChanged(null),
        ),
        for (final voice in VoicePart.values)
          _VoicePill(
            label: voice.label,
            color: VoiceMixerSheet.pillColors[voice]!,
            selected: voice == selected,
            onTap: () => onChanged(voice),
          ),
      ],
    );
  }
}

class _VoicePill extends StatelessWidget {
  const _VoicePill({
    required this.label,
    required this.color,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final Color color;
  final bool selected;
  final VoidCallback onTap;

  static const double _height = kMinInteractiveDimension;
  static const double _horizontalPadding = 16;
  static const double _outlineWidth = 1.5;
  static const double _checkSize = 18;
  static const double _checkGap = 6;
  static const double _fontSize = 15;
  static const Duration _animation = Duration(milliseconds: 150);

  @override
  Widget build(BuildContext context) {
    final foreground = selected ? Colors.white : color;
    final shape = StadiumBorder(
      side: BorderSide(color: color, width: _outlineWidth),
    );

    return Semantics(
      button: true,
      selected: selected,
      inMutuallyExclusiveGroup: true,
      label: SettingsMessages.voiceSemantics(label),
      excludeSemantics: true,
      onTap: onTap,
      child: AnimatedContainer(
        duration: _animation,
        constraints: const BoxConstraints(minHeight: _height),
        decoration: ShapeDecoration(
          color: selected ? color : Colors.white,
          shape: shape,
        ),
        child: Material(
          type: MaterialType.transparency,
          shape: shape,
          clipBehavior: Clip.antiAlias,
          child: InkWell(
            onTap: onTap,
            child: Padding(
              padding: const EdgeInsets.symmetric(
                horizontal: _horizontalPadding,
              ),
              child: ConstrainedBox(
                constraints: const BoxConstraints(minHeight: _height),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.center,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    if (selected) ...[
                      Icon(
                        Icons.check_rounded,
                        size: _checkSize,
                        color: foreground,
                      ),
                      const SizedBox(width: _checkGap),
                    ],
                    // A pill alone on its line at 2x text on a 320 dp
                    // phone is still narrower than "✓ Soprano"; the name
                    // wraps (the pill grows taller) rather than overflow.
                    Flexible(
                      child: Text(
                        label,
                        textAlign: TextAlign.center,
                        style: Theme.of(context).textTheme.labelLarge?.copyWith(
                          fontSize: _fontSize,
                          fontWeight: FontWeight.w600,
                          color: foreground,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
