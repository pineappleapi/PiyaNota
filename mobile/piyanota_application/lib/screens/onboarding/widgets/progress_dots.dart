import 'package:flutter/material.dart';

import '../../../theme/app_theme.dart';

class ProgressDots extends StatelessWidget {
  const ProgressDots({
    super.key,
    required this.stepCount,
    required this.currentStep,
  });

  final int stepCount;
  final int currentStep;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: List.generate(stepCount, (index) {
        final isActive = index == currentStep;
        return AnimatedContainer(
          duration: const Duration(milliseconds: 200),
          margin: const EdgeInsets.symmetric(horizontal: 4),
          width: 8,
          height: 8,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: isActive ? AppTheme.dotActive : AppTheme.dotInactive,
          ),
        );
      }),
    );
  }
}
