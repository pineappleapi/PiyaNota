import 'package:flutter/material.dart';

import '../widgets/onboarding_heading_block.dart';

/// Step 2 (PIYA-201 AC2): the 3-step Capture → Wait → Listen workflow.
class WorkflowStep extends StatelessWidget {
  const WorkflowStep({super.key});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 32),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const OnboardingHeadingBlock(
            title: 'How It Works',
            subtitle: 'Three simple steps from page to playback.',
          ),
          const SizedBox(height: 40),
          const _WorkflowRow(
            icon: Icons.camera_alt_outlined,
            label: 'Capture',
            description: 'Photograph an open-score SATB page.',
          ),
          const SizedBox(height: 24),
          const _WorkflowRow(
            icon: Icons.hourglass_top_outlined,
            label: 'Wait',
            description: 'PiyaNota transcribes and separates each voice.',
          ),
          const SizedBox(height: 24),
          const _WorkflowRow(
            icon: Icons.headphones_outlined,
            label: 'Listen',
            description: 'Play back your voice part on demand.',
          ),
        ],
      ),
    );
  }
}

class _WorkflowRow extends StatelessWidget {
  const _WorkflowRow({
    required this.icon,
    required this.label,
    required this.description,
  });

  final IconData icon;
  final String label;
  final String description;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;

    return Row(
      children: [
        Container(
          width: 52,
          height: 52,
          decoration: BoxDecoration(
            color: Colors.white.withValues(alpha: 0.15),
            shape: BoxShape.circle,
          ),
          child: Icon(icon, color: Colors.white, size: 26),
        ),
        const SizedBox(width: 16),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                label,
                style: textTheme.titleMedium?.copyWith(
                  color: Colors.white,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                description,
                style: textTheme.bodySmall?.copyWith(
                  color: Colors.white.withValues(alpha: 0.9),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
