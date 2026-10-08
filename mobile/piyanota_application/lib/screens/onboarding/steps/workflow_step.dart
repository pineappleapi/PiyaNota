import 'package:flutter/material.dart';

import '../../../theme/app_theme.dart';
import '../widgets/onboarding_heading_block.dart';

/// Step 2 (PIYA-201 AC2): the 3-step Capture → Wait → Listen workflow.
class WorkflowStep extends StatelessWidget {
  const WorkflowStep({super.key});

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 32),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Expanded(
                child: _WorkflowTile(
                  color: AppTheme.workflowTileCapture,
                  icon: Icons.camera_alt_outlined,
                  step: 1,
                  label: 'CAPTURE',
                ),
              ),
              SizedBox(width: 12),
              Expanded(
                child: _WorkflowTile(
                  color: AppTheme.workflowTileWait,
                  icon: Icons.autorenew,
                  step: 2,
                  label: 'WAIT',
                ),
              ),
              SizedBox(width: 12),
              Expanded(
                child: _WorkflowTile(
                  color: AppTheme.workflowTileListen,
                  icon: Icons.headphones_outlined,
                  step: 3,
                  label: 'LISTEN',
                ),
              ),
            ],
          ),
          const SizedBox(height: 32),
          OnboardingHeadingBlock(
            titleSpans: [
              const TextSpan(text: 'Three steps.\n'),
              gradientTitleLine(
                "That's all it takes.",
                textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700),
              ),
            ],
            subtitle:
                'Photograph your score and get audio in minutes — '
                'then use it to follow along, learn your part, and build '
                'your reading skills.',
          ),
        ],
      ),
    );
  }
}

class _WorkflowTile extends StatelessWidget {
  const _WorkflowTile({
    required this.color,
    required this.icon,
    required this.step,
    required this.label,
  });

  final Color color;
  final IconData icon;
  final int step;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 160,
      padding: const EdgeInsets.symmetric(vertical: 16),
      decoration: BoxDecoration(
        color: color,
        borderRadius: BorderRadius.circular(20),
      ),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.spaceEvenly,
        children: [
          Icon(icon, color: Colors.white, size: 32),
          Container(
            width: 24,
            height: 24,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: Colors.white.withValues(alpha: 0.3),
            ),
            alignment: Alignment.center,
            child: Text(
              '$step',
              style: const TextStyle(
                color: Colors.white,
                fontWeight: FontWeight.w700,
                fontSize: 13,
              ),
            ),
          ),
          Text(
            label,
            style: const TextStyle(
              color: Colors.white,
              fontWeight: FontWeight.w700,
              fontSize: 12,
              letterSpacing: 0.5,
            ),
          ),
        ],
      ),
    );
  }
}
