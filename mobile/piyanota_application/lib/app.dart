import 'package:flutter/material.dart';

import 'theme/app_theme.dart';

/// Root widget. Route table is populated as PIYA-201+ screens land.
class PiyaNotaApp extends StatelessWidget {
  const PiyaNotaApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'PiyaNota',
      theme: AppTheme.light,
      home: const _ScaffoldPlaceholder(),
    );
  }
}

class _ScaffoldPlaceholder extends StatelessWidget {
  const _ScaffoldPlaceholder();

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      body: Center(child: Text('PiyaNota')),
    );
  }
}
