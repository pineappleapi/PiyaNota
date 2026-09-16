import 'package:flutter/material.dart';

/// Shared title/subtitle layout used by every onboarding content step, so
/// spacing and type styling stay identical across the three steps.
class OnboardingHeadingBlock extends StatelessWidget {
  const OnboardingHeadingBlock({
    super.key,
    required this.title,
    required this.subtitle,
    this.titleColor = Colors.white,
    this.subtitleColor = Colors.white,
  });

  final String title;
  final String subtitle;
  final Color titleColor;
  final Color subtitleColor;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        Text(
          title,
          textAlign: TextAlign.center,
          style: textTheme.headlineSmall?.copyWith(
            fontWeight: FontWeight.w700,
            color: titleColor,
          ),
        ),
        const SizedBox(height: 12),
        Text(
          subtitle,
          textAlign: TextAlign.center,
          style: textTheme.bodyMedium?.copyWith(
            color: subtitleColor.withValues(alpha: 0.9),
          ),
        ),
      ],
    );
  }
}
