import 'package:flutter/material.dart';

/// Stand-in destination for screens not yet built (PIYA-202/203 etc.) so
/// that onboarding's routing has somewhere real to land. Replace each call
/// site with the real screen as its ticket lands.
class ComingSoonScreen extends StatelessWidget {
  const ComingSoonScreen({super.key, required this.title});

  final String title;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(title)),
      body: Center(
        child: Text(
          '$title — coming soon',
          style: Theme.of(context).textTheme.titleMedium,
        ),
      ),
    );
  }
}
