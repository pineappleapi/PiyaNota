import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../../theme/app_theme.dart';

/// Pill-shaped, borderless filled input from the PIYA-202 reference. A brand
/// focus ring is added (the reference shows none) so keyboard/TalkBack users
/// can tell which field is active.
class AuthTextField extends StatelessWidget {
  const AuthTextField({
    super.key,
    required this.controller,
    required this.hintText,
    required this.icon,
    this.keyboardType,
    this.textInputAction,
    this.autofillHints,
    this.obscureText = false,
    this.enabled = true,
    this.validator,
    this.onFieldSubmitted,
    this.helperText,
    this.suffixIcon,
    this.inputFormatters,
  });

  final TextEditingController controller;
  final String hintText;
  final IconData icon;
  final TextInputType? keyboardType;
  final TextInputAction? textInputAction;
  final Iterable<String>? autofillHints;
  final bool obscureText;
  final bool enabled;
  final FormFieldValidator<String>? validator;
  final ValueChanged<String>? onFieldSubmitted;
  final String? helperText;
  final Widget? suffixIcon;
  final List<TextInputFormatter>? inputFormatters;

  static const double _focusBorderWidth = 1.5;
  static const EdgeInsets _contentPadding = EdgeInsets.symmetric(
    horizontal: 20,
    vertical: 18,
  );
  static const int _maxMessageLines = 2;

  static OutlineInputBorder _pill([BorderSide side = BorderSide.none]) {
    return OutlineInputBorder(
      borderRadius: BorderRadius.circular(999),
      borderSide: side,
    );
  }

  @override
  Widget build(BuildContext context) {
    return TextFormField(
      controller: controller,
      keyboardType: keyboardType,
      textInputAction: textInputAction,
      autofillHints: autofillHints,
      obscureText: obscureText,
      enabled: enabled,
      validator: validator,
      onFieldSubmitted: onFieldSubmitted,
      inputFormatters: inputFormatters,
      autocorrect: false,
      enableSuggestions: !obscureText,
      decoration: InputDecoration(
        hintText: hintText,
        hintStyle: const TextStyle(color: AppTheme.authHintText),
        prefixIcon: Icon(icon, color: AppTheme.authFieldIcon),
        suffixIcon: suffixIcon,
        helperText: helperText,
        helperMaxLines: _maxMessageLines,
        errorMaxLines: _maxMessageLines,
        filled: true,
        fillColor: AppTheme.authFieldFill,
        contentPadding: _contentPadding,
        border: _pill(),
        enabledBorder: _pill(),
        disabledBorder: _pill(),
        focusedBorder: _pill(
          const BorderSide(
            color: AppTheme.primaryBlue,
            width: _focusBorderWidth,
          ),
        ),
        errorBorder: _pill(const BorderSide(color: AppTheme.errorRed)),
        focusedErrorBorder: _pill(
          const BorderSide(color: AppTheme.errorRed, width: _focusBorderWidth),
        ),
      ),
    );
  }
}

/// [AuthTextField] with the reference's show/hide eye toggle.
class AuthPasswordField extends StatefulWidget {
  const AuthPasswordField({
    super.key,
    required this.controller,
    required this.hintText,
    this.textInputAction,
    this.autofillHints,
    this.enabled = true,
    this.validator,
    this.onFieldSubmitted,
    this.helperText,
  });

  final TextEditingController controller;
  final String hintText;
  final TextInputAction? textInputAction;
  final Iterable<String>? autofillHints;
  final bool enabled;
  final FormFieldValidator<String>? validator;
  final ValueChanged<String>? onFieldSubmitted;
  final String? helperText;

  @override
  State<AuthPasswordField> createState() => _AuthPasswordFieldState();
}

class _AuthPasswordFieldState extends State<AuthPasswordField> {
  bool _obscured = true;

  @override
  Widget build(BuildContext context) {
    return AuthTextField(
      controller: widget.controller,
      hintText: widget.hintText,
      icon: Icons.lock_outline_rounded,
      keyboardType: TextInputType.visiblePassword,
      textInputAction: widget.textInputAction,
      autofillHints: widget.autofillHints,
      obscureText: _obscured,
      enabled: widget.enabled,
      validator: widget.validator,
      onFieldSubmitted: widget.onFieldSubmitted,
      helperText: widget.helperText,
      suffixIcon: IconButton(
        onPressed: () => setState(() => _obscured = !_obscured),
        tooltip: _obscured ? 'Show password' : 'Hide password',
        icon: Icon(
          _obscured
              ? Icons.visibility_off_outlined
              : Icons.visibility_outlined,
          color: AppTheme.authFieldIcon,
        ),
      ),
    );
  }
}
