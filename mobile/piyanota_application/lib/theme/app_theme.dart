import 'package:flutter/material.dart';

/// Central theme definition. Colors/typography TBD per design tickets;
/// this seed keeps the app buildable until then.
class AppTheme {
  AppTheme._();

  static ThemeData get light => ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.deepPurple),
      );
}
