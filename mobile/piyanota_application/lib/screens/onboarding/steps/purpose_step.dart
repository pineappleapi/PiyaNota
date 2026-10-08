import 'package:flutter/material.dart';

import '../../../theme/app_theme.dart';
import '../widgets/onboarding_heading_block.dart';

/// Step 1 (PIYA-201 AC2): explains what PiyaNota does — turns photographed
/// SATB sheet music into per-voice playable audio.
class PurposeStep extends StatelessWidget {
  const PurposeStep({super.key});

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 32),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Approximated with layered Material icons on the brand gradient —
          // no vector asset exists for the reference's custom document/
          // headphones line art.
          Container(
            width: double.infinity,
            height: 160,
            decoration: BoxDecoration(
              gradient: AppTheme.primaryGradient,
              borderRadius: BorderRadius.circular(24),
            ),
            child: const Row(
              mainAxisAlignment: MainAxisAlignment.spaceEvenly,
              children: [
                Icon(Icons.description_outlined, color: Colors.white, size: 56),
                Icon(Icons.arrow_forward, color: Colors.white, size: 28),
                Icon(Icons.headphones, color: Colors.white, size: 56),
              ],
            ),
          ),
          const SizedBox(height: 32),
          OnboardingHeadingBlock(
            titleSpans: [
              const TextSpan(text: 'Notes on a page,\n'),
              gradientTitleLine(
                'Music in your ears',
                textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Text.rich(
            TextSpan(
              style: textTheme.bodyMedium?.copyWith(
                color: AppTheme.onboardingBody,
              ),
              children: const [
                TextSpan(
                  text: 'PiyaNota',
                  style: TextStyle(fontWeight: FontWeight.w700),
                ),
                TextSpan(
                  text:
                      ' turns your printed choir sheet music into playable '
                      'audio — perfect for beginners and seasoned singers '
                      'alike.',
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
