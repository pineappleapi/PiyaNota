import 'package:flutter/material.dart';

import '../../../theme/app_theme.dart';

const _dividerWidth = 40.0;
const _dividerHeight = 4.0;

/// Shared title/subtitle layout used by every onboarding content step, so
/// spacing and type styling stay identical across the three steps.
///
/// [titleSpans] carries the two-line, mixed dark/accent heading text as rich
/// spans rather than a single string, since step 3's heading colors only one
/// word mid-line ("do you sing?") while steps 1/2 color a whole second line.
class OnboardingHeadingBlock extends StatelessWidget {
  const OnboardingHeadingBlock({
    super.key,
    required this.titleSpans,
    this.subtitle,
  });

  final List<InlineSpan> titleSpans;

  /// Plain-text body copy. Leave null when the caller renders its own rich
  /// body text below instead (e.g. to bold part of it).
  final String? subtitle;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Container(
          width: _dividerWidth,
          height: _dividerHeight,
          decoration: BoxDecoration(
            color: AppTheme.primaryBlue,
            borderRadius: BorderRadius.circular(_dividerHeight / 2),
          ),
        ),
        const SizedBox(height: 16),
        Text.rich(
          TextSpan(
            style: textTheme.headlineSmall?.copyWith(
              fontWeight: FontWeight.w700,
              color: AppTheme.onboardingHeadingDark,
              height: 1.25,
            ),
            children: titleSpans,
          ),
        ),
        if (subtitle != null) ...[
          const SizedBox(height: 12),
          Text(
            subtitle!,
            style: textTheme.bodyMedium?.copyWith(
              color: AppTheme.onboardingBody,
            ),
          ),
        ],
      ],
    );
  }
}

/// A whole-line accent heading, shaded with the real brand gradient rather
/// than [AppTheme.onboardingAccent]'s flat approximation — used where the
/// entire second heading line is the accent color (steps 1 and 2).
InlineSpan gradientTitleLine(String text, TextStyle? baseStyle) {
  return WidgetSpan(
    alignment: PlaceholderAlignment.middle,
    child: ShaderMask(
      shaderCallback: (bounds) => AppTheme.primaryGradient.createShader(
        Rect.fromLTWH(0, 0, bounds.width, bounds.height),
      ),
      child: Text(text, style: baseStyle?.copyWith(color: Colors.white)),
    ),
  );
}
