import 'package:flutter/material.dart';

import '../widgets/onboarding_heading_block.dart';

/// Step 1 (PIYA-201 AC2): explains what PiyaNota does — turns photographed
/// SATB sheet music into per-voice playable audio.
class PurposeStep extends StatelessWidget {
  const PurposeStep({super.key});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 32),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Container(
            width: 160,
            height: 160,
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.15),
              shape: BoxShape.circle,
            ),
            child: const Icon(
              Icons.library_music_outlined,
              size: 84,
              color: Colors.white,
            ),
          ),
          const SizedBox(height: 40),
          const OnboardingHeadingBlock(
            title: 'Turn Sheet Music Into Sound',
            subtitle:
                'PiyaNota reads photos of your SATB choral scores and turns '
                'them into separate Soprano, Alto, Tenor, and Bass audio '
                'tracks — so every voice part can hear their line.',
          ),
        ],
      ),
    );
  }
}
