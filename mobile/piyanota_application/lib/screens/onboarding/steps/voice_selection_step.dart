import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../models/voice_part.dart';
import '../../../state/onboarding_providers.dart';
import '../../../theme/app_theme.dart';
import '../widgets/onboarding_heading_block.dart';

/// Step 3 (PIYA-201 AC2, AC5): pick a default voice part. Selection is held
/// in [selectedVoicePartProvider] and persisted when onboarding completes.
class VoiceSelectionStep extends ConsumerWidget {
  const VoiceSelectionStep({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final selected = ref.watch(selectedVoicePartProvider);

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 32),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const OnboardingHeadingBlock(
            title: 'Choose Your Voice Part',
            subtitle: 'We’ll use this as your default playback track. '
                'You can change it anytime.',
          ),
          const SizedBox(height: 32),
          GridView.count(
            crossAxisCount: 2,
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            mainAxisSpacing: 16,
            crossAxisSpacing: 16,
            childAspectRatio: 1.4,
            children: VoicePart.values.map((part) {
              final isSelected = selected == part;
              final accent = AppTheme.voiceAccents[part]!;

              return _VoiceCard(
                label: part.label,
                background: accent.background,
                iconColor: accent.icon,
                isSelected: isSelected,
                onTap: () =>
                    ref.read(selectedVoicePartProvider.notifier).select(part),
              );
            }).toList(),
          ),
        ],
      ),
    );
  }
}

class _VoiceCard extends StatelessWidget {
  const _VoiceCard({
    required this.label,
    required this.background,
    required this.iconColor,
    required this.isSelected,
    required this.onTap,
  });

  final String label;
  final Color background;
  final Color iconColor;
  final bool isSelected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(20),
        splashColor: AppTheme.darken(background, 0.08),
        highlightColor: AppTheme.darken(background, 0.08),
        child: Container(
          decoration: BoxDecoration(
            color: background,
            borderRadius: BorderRadius.circular(20),
            border: Border.all(
              color: isSelected ? Colors.white : Colors.transparent,
              width: 3,
            ),
          ),
          alignment: Alignment.center,
          child: Text(
            label,
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
                  color: iconColor,
                  fontWeight: FontWeight.w700,
                ),
          ),
        ),
      ),
    );
  }
}
