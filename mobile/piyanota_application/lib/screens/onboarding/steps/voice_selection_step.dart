import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../models/voice_part.dart';
import '../../../state/onboarding_providers.dart';
import '../../../theme/app_theme.dart';
import '../widgets/onboarding_heading_block.dart';

const _cardBorder = Color(0xFFE0E0E0);
const _conductorLabel = "I'm a Conductor / I'm not sure yet";
const _conductorButtonBorder = Color(0xFFDBDBDB);

/// Step 3 (PIYA-201 AC2, AC5): pick a default voice part. Selection is held
/// in [selectedVoicePartProvider] and persisted when onboarding completes.
///
/// PIYA-201-V2.1: "I'm a Conductor / I'm not sure yet" is a selectable fifth
/// option (single choice with the four voices, see
/// [conductorSelectedProvider]). It no longer leaves the step; the Get
/// Started button does. Selected means no default voice is persisted, so
/// Playback opens with all four voices on.
class VoiceSelectionStep extends ConsumerWidget {
  const VoiceSelectionStep({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final selected = ref.watch(selectedVoicePartProvider);
    final conductorSelected = ref.watch(conductorSelectedProvider);
    final textTheme = Theme.of(context).textTheme;

    return LayoutBuilder(
      builder: (context, constraints) => SingleChildScrollView(
        padding: const EdgeInsets.symmetric(horizontal: 32),
        child: ConstrainedBox(
          constraints: BoxConstraints(minHeight: constraints.maxHeight),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              OnboardingHeadingBlock(
                titleSpans: [
                  const TextSpan(text: 'What part\ndo you '),
                  TextSpan(
                    text: 'sing',
                    style: TextStyle(color: AppTheme.onboardingAccent),
                  ),
                  const TextSpan(text: '?'),
                ],
                subtitle:
                    "We'll remember your part so it's the first thing "
                    'you hear.',
              ),
              const SizedBox(height: 24),
              GridView.count(
                crossAxisCount: 2,
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                mainAxisSpacing: 16,
                crossAxisSpacing: 16,
                childAspectRatio: 1.5,
                children: VoicePart.values.map((part) {
                  final isSelected = selected == part;
                  final badgeColor = AppTheme.voiceAccents[part]!;

                  return _VoiceCard(
                    label: part.label,
                    badgeColor: badgeColor,
                    isSelected: isSelected,
                    onTap: () {
                      ref.read(conductorSelectedProvider.notifier).set(false);
                      ref.read(selectedVoicePartProvider.notifier).select(part);
                    },
                  );
                }).toList(),
              ),
              const SizedBox(height: 16),
              SizedBox(
                width: double.infinity,
                child: Semantics(
                  selected: conductorSelected,
                  button: true,
                  excludeSemantics: true,
                  label: _conductorLabel,
                  child: OutlinedButton(
                    onPressed: () {
                      ref.read(selectedVoicePartProvider.notifier).clear();
                      ref.read(conductorSelectedProvider.notifier).set(true);
                    },
                    style: OutlinedButton.styleFrom(
                      // Same selected look as _VoiceCard.
                      side: BorderSide(
                        color: conductorSelected
                            ? AppTheme.primaryBlue
                            : _conductorButtonBorder,
                        width: conductorSelected ? 2 : 1,
                      ),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(999),
                      ),
                      padding: const EdgeInsets.symmetric(vertical: 16),
                    ),
                    child: Text(
                      _conductorLabel,
                      style: textTheme.bodyMedium?.copyWith(
                        color: AppTheme.onboardingHeadingDark,
                        decoration: TextDecoration.underline,
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _VoiceCard extends StatelessWidget {
  const _VoiceCard({
    required this.label,
    required this.badgeColor,
    required this.isSelected,
    required this.onTap,
  });

  final String label;
  final Color badgeColor;
  final bool isSelected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      selected: isSelected,
      button: true,
      excludeSemantics: true,
      label: label,
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(16),
          child: Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(16),
              border: Border.all(
                color: isSelected ? AppTheme.primaryBlue : _cardBorder,
                width: isSelected ? 2 : 1,
              ),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Container(
                      width: 44,
                      height: 44,
                      decoration: BoxDecoration(
                        color: badgeColor,
                        shape: BoxShape.circle,
                      ),
                      child: const Icon(
                        Icons.mic,
                        color: Colors.white,
                        size: 22,
                      ),
                    ),
                    Container(
                      width: 18,
                      height: 18,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        border: Border.all(
                          color: isSelected
                              ? AppTheme.primaryBlue
                              : _cardBorder,
                          width: 2,
                        ),
                        color: isSelected ? AppTheme.primaryBlue : null,
                      ),
                    ),
                  ],
                ),
                const Spacer(),
                Text(
                  label,
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    color: AppTheme.onboardingHeadingDark,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
