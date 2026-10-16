import 'package:flutter/material.dart';

import '../../../models/voice_part.dart';
import '../../playback/mixer_sheet.dart';
import '../settings_messages.dart';

/// PIYA-212 AC7: the four voices as single-select pills in their Voice
/// Mixer colours, so the choice looks like the voice it turns on in
/// Playback. The chosen pill is filled with a white tick; the rest are
/// outlined in their colour. Every mixer colour is 4.5:1 against white
/// either way round (see AppTheme.mixerSoprano), so both states pass AA.
class VoicePicker extends StatelessWidget {
  const VoicePicker({
    super.key,
    required this.selected,
    required this.onChanged,
  });

  /// Null when none was ever chosen (onboarding skipped).
  final VoicePart? selected;
  final ValueChanged<VoicePart> onChanged;

  static const double _gap = 8;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: _gap,
      runSpacing: _gap,
      children: [
        for (final voice in VoicePart.values)
          _VoicePill(
            voice: voice,
            selected: voice == selected,
            onTap: () => onChanged(voice),
          ),
      ],
    );
  }
}

class _VoicePill extends StatelessWidget {
  const _VoicePill({
    required this.voice,
    required this.selected,
    required this.onTap,
  });

  final VoicePart voice;
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
    final color = VoiceMixerSheet.pillColors[voice]!;
    final foreground = selected ? Colors.white : color;
    final shape = StadiumBorder(
      side: BorderSide(color: color, width: _outlineWidth),
    );

    return Semantics(
      button: true,
      selected: selected,
      inMutuallyExclusiveGroup: true,
      label: SettingsMessages.voiceSemantics(voice.label),
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
                        voice.label,
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
