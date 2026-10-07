import 'package:flutter/material.dart';

/// Stand-in destination for screens not yet built (PIYA-202/203 etc.) so
/// that onboarding's routing has somewhere real to land. Replace each call
/// site with the real screen as its ticket lands.
class ComingSoonScreen extends StatelessWidget {
  const ComingSoonScreen({super.key, required this.title, this.detail});

  final String title;

  /// Optional context line, e.g. which score Playback was opened for, so a
  /// tester can confirm the right arguments arrived before the real screen
  /// exists.
  final String? detail;

  static const double _detailGap = 8;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    final detailText = detail;

    return Scaffold(
      appBar: AppBar(title: Text(title)),
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('$title — coming soon', style: textTheme.titleMedium),
            if (detailText != null) ...[
              const SizedBox(height: _detailGap),
              Text(
                detailText,
                textAlign: TextAlign.center,
                style: textTheme.bodyMedium,
              ),
            ],
          ],
        ),
      ),
    );
  }
}
