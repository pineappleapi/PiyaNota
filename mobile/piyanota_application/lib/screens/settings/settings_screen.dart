import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/score_details.dart';
import '../../models/voice_part.dart';
import '../../routes/app_routes.dart';
import '../../state/auth_providers.dart';
import '../../state/onboarding_providers.dart';
import '../../state/session_actions.dart';
import '../../state/settings_providers.dart';
import '../../theme/app_theme.dart';
import '../library/widgets/library_bottom_nav.dart';
import '../library/widgets/library_header.dart';
import 'settings_messages.dart';
import 'widgets/change_password_sheet.dart';
import 'widgets/help_button.dart';
import 'widgets/log_out_dialog.dart';
import 'widgets/settings_section.dart';
import 'widgets/tempo_stepper.dart';
import 'widgets/voice_picker.dart';

/// PIYA-212 AC5: Settings opens only on a live session. The check runs
/// before any account detail is drawn, so an expired session never flashes
/// the previous user's email on its way to Login.
class SettingsGate extends ConsumerStatefulWidget {
  const SettingsGate({super.key});

  @override
  ConsumerState<SettingsGate> createState() => _SettingsGateState();
}

class _SettingsGateState extends ConsumerState<SettingsGate> {
  late final Future<bool> _valid = _check();

  Future<bool> _check() async {
    bool valid;
    try {
      valid = await ref.read(sessionStorageProvider).hasValidSession();
    } catch (e, stack) {
      // Unreadable storage can't prove a session, so treat it as none.
      debugPrint('Session check failed: $e\n$stack');
      valid = false;
    }
    if (!valid) {
      await endLocalSession(ref);
      if (mounted) {
        Navigator.of(context)
            .pushNamedAndRemoveUntil(AppRoutes.login, (_) => false);
      }
    }
    return valid;
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<bool>(
      future: _valid,
      builder: (context, snapshot) => snapshot.data == true
          ? const SettingsScreen()
          // The check is a local read (a few ms); a blank page in the
          // library colour avoids a spinner flash.
          : const ColoredBox(color: AppTheme.libraryBackground),
    );
  }
}

/// PIYA-212: account (email, change password), playback defaults (voice,
/// tempo, each with help) and About (version), then Log out. Drawn with the
/// Library's header and bottom bar so it reads as the bar's second tab.
class SettingsScreen extends ConsumerStatefulWidget {
  const SettingsScreen({super.key});

  @override
  ConsumerState<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends ConsumerState<SettingsScreen> {
  // Same side margins as the Library cards (see ScoreLibraryScreen).
  static const double _marginFraction = 32 / 412;
  static const double _maxMargin = 32;
  static const double _minMargin = 16;
  static const double _headerInsetFromCards = 6;
  static const double _listTopGap = 24;
  static const double _groupGap = 24;
  static const double _bottomGap = 18;
  static const double _snackBarSideMargin = 16;
  static const double _captionGap = 2;
  static const double _controlGap = 12;
  static const double _rowIconSize = 22;
  static const double _logOutRadius = 16;

  VoicePart? _voice;
  int _tempo = ScoreDetails.defaultTempo;
  int _savedTempo = ScoreDetails.defaultTempo;
  int _tempoSaveSeq = 0;
  bool _prefsLoaded = false;

  @override
  void initState() {
    super.initState();
    _loadPrefs();
  }

  Future<void> _loadPrefs() async {
    VoicePart? voice;
    var tempo = ScoreDetails.defaultTempo;
    try {
      voice = await ref
          .read(onboardingPrefsServiceProvider)
          .getDefaultVoicePart();
      tempo = await ref.read(settingsPrefsServiceProvider).getDefaultTempo();
    } catch (e, stack) {
      // Shown at their defaults; a later change still tries to save.
      debugPrint('Settings prefs unreadable: $e\n$stack');
    }
    if (!mounted) return;
    setState(() {
      _voice = voice;
      _tempo = tempo;
      _savedTempo = tempo;
      _prefsLoaded = true;
    });
  }

  Future<void> _setVoice(VoicePart voice) async {
    final previous = _voice;
    if (voice == previous) return;
    setState(() => _voice = voice);
    try {
      await ref.read(onboardingPrefsServiceProvider).setDefaultVoicePart(voice);
    } catch (e, stack) {
      debugPrint('Default voice not saved: $e\n$stack');
      if (!mounted) return;
      setState(() => _voice = previous);
      _showSnackBar(SettingsMessages.saveFailed);
    }
  }

  /// Every step of a held button: display only, so a hold saves once.
  void _showTempo(int bpm) => setState(() => _tempo = bpm);

  /// Once per tap or per hold. A failure rolls back to [_savedTempo], the
  /// last value known to be on disk, not to the value before this gesture,
  /// which may itself never have saved.
  Future<void> _commitTempo(int bpm) async {
    final attempt = ++_tempoSaveSeq;
    try {
      await ref.read(settingsPrefsServiceProvider).setDefaultTempo(bpm);
      // SharedPreferences applies writes in call order, so a success here
      // means bpm is what is stored now unless a later save follows it.
      if (attempt == _tempoSaveSeq) _savedTempo = bpm;
    } catch (e, stack) {
      debugPrint('Default tempo not saved: $e\n$stack');
      // Only the latest gesture may roll back; an older failure must not
      // undo a newer value the user is now looking at.
      if (!mounted || attempt != _tempoSaveSeq) return;
      setState(() => _tempo = _savedTempo);
      _showSnackBar(SettingsMessages.saveFailed);
    }
  }

  Future<void> _changePassword() async {
    final result = await showChangePasswordSheet(context);
    if (!mounted) return;
    switch (result) {
      case ChangePasswordResult.changed:
        _showSnackBar(SettingsMessages.passwordChanged);
      case ChangePasswordResult.logInAgain:
        await _toLogin();
      case null:
        break;
    }
  }

  Future<void> _logOut() async {
    if (!await confirmLogOut(context) || !mounted) return;
    // PIYA-305 (server logout) is wired by PIYA-217; until then the token
    // is only dropped here and lapses server-side at its own expiry.
    await _toLogin();
  }

  Future<void> _toLogin() async {
    await endLocalSession(ref);
    if (!mounted) return;
    Navigator.of(context)
        .pushNamedAndRemoveUntil(AppRoutes.login, (_) => false);
  }

  void _showSnackBar(String message) {
    final navHeight = LibraryBottomNav.heightFor(
      MediaQuery.paddingOf(context).bottom,
    );
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(
        SnackBar(
          content: Text(message),
          behavior: SnackBarBehavior.floating,
          // Above the custom bar, which Scaffold doesn't know about.
          margin: EdgeInsets.fromLTRB(
            _snackBarSideMargin,
            0,
            _snackBarSideMargin,
            navHeight,
          ),
        ),
      );
  }

  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    final margin = (width * _marginFraction)
        .clamp(_minMargin, _maxMargin)
        .toDouble();
    final navHeight = LibraryBottomNav.heightFor(
      MediaQuery.paddingOf(context).bottom,
    );

    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: SystemUiOverlayStyle.light,
      child: Scaffold(
        backgroundColor: AppTheme.libraryBackground,
        resizeToAvoidBottomInset: false,
        body: Stack(
          children: [
            Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                _SettingsHeader(
                  horizontalPadding: margin - _headerInsetFromCards,
                ),
                Expanded(
                  child: ListView(
                    padding: EdgeInsets.fromLTRB(
                      margin,
                      _listTopGap,
                      margin,
                      navHeight + _bottomGap,
                    ),
                    children: [
                      _accountSection(context),
                      const SizedBox(height: _groupGap),
                      _playbackSection(context),
                      const SizedBox(height: _groupGap),
                      _aboutSection(context),
                      const SizedBox(height: _groupGap),
                      _logOutRow(context),
                    ],
                  ),
                ),
              ],
            ),
            Positioned(
              left: 0,
              right: 0,
              bottom: 0,
              child: LibraryBottomNav(
                selected: LibraryNavTab.settings,
                // Settings is always pushed over the Library.
                onLibrary: () => Navigator.of(context).maybePop(),
                onCapture: () =>
                    Navigator.of(context)
                        .pushReplacementNamed(AppRoutes.capture),
                onSettings: () {},
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _accountSection(BuildContext context) {
    final email = ref.watch(accountEmailProvider);
    final address = email.value;
    return SettingsSection(
      title: SettingsMessages.accountGroup,
      children: [
        Padding(
          padding: kSettingsRowPadding,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                SettingsMessages.email,
                style: SettingsText.caption(context),
              ),
              const SizedBox(height: _captionGap),
              if (email.isLoading)
                const SizedBox.shrink()
              else if (address == null || address.isEmpty)
                Text(
                  SettingsMessages.emailUnknown,
                  style: SettingsText.caption(context),
                )
              else
                // Read-only (AC1) but copyable, for a tester reporting it.
                SelectableText(
                  address,
                  key: const ValueKey('settings-email'),
                  style: SettingsText.value(context),
                ),
            ],
          ),
        ),
        InkWell(
          onTap: _changePassword,
          child: Padding(
            padding: kSettingsRowPadding,
            child: Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        SettingsMessages.changePassword,
                        style: SettingsText.label(context),
                      ),
                      const SizedBox(height: _captionGap),
                      Text(
                        SettingsMessages.changePasswordHint,
                        style: SettingsText.caption(context),
                      ),
                    ],
                  ),
                ),
                const Icon(
                  Icons.chevron_right_rounded,
                  size: _rowIconSize,
                  color: AppTheme.settingsSubtle,
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }

  Widget _playbackSection(BuildContext context) {
    return SettingsSection(
      title: SettingsMessages.playbackGroup,
      children: [
        _PreferenceRow(
          label: SettingsMessages.defaultVoice,
          caption: SettingsMessages.defaultVoiceCaption,
          help: const HelpButton(
            key: ValueKey('settings-voice-help'),
            tooltip: SettingsMessages.voiceHelpTooltip,
            title: SettingsMessages.defaultVoice,
            body: SettingsMessages.voiceHelpBody,
          ),
          control: _prefsLoaded
              ? VoicePicker(selected: _voice, onChanged: _setVoice)
              : null,
          controlGap: _controlGap,
        ),
        _PreferenceRow(
          label: SettingsMessages.defaultTempo,
          caption: SettingsMessages.defaultTempoCaption,
          help: const HelpButton(
            key: ValueKey('settings-tempo-help'),
            tooltip: SettingsMessages.tempoHelpTooltip,
            title: SettingsMessages.defaultTempo,
            body: SettingsMessages.tempoHelpBody,
          ),
          control: _prefsLoaded
              ? TempoStepper(
                  value: _tempo,
                  onChanged: _showTempo,
                  onCommit: _commitTempo,
                )
              : null,
          controlGap: _controlGap,
        ),
      ],
    );
  }

  Widget _aboutSection(BuildContext context) {
    final version = ref.watch(appVersionProvider);
    // hasError before value: a retrying provider can carry both.
    final text = version.hasError
        ? SettingsMessages.versionUnknown
        : version.value ?? '';
    return SettingsSection(
      title: SettingsMessages.aboutGroup,
      children: [
        Padding(
          padding: kSettingsRowPadding,
          child: Row(
            children: [
              Expanded(
                child: Text(
                  SettingsMessages.appVersion,
                  style: SettingsText.label(context),
                ),
              ),
              const SizedBox(width: _controlGap),
              Flexible(
                child: Text(
                  text,
                  key: const ValueKey('settings-version'),
                  textAlign: TextAlign.end,
                  style: SettingsText.value(context),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _logOutRow(BuildContext context) {
    return Material(
      color: AppTheme.settingsSurface,
      borderRadius: BorderRadius.circular(_logOutRadius),
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: _logOut,
        child: Padding(
          padding: kSettingsRowPadding,
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(
                Icons.logout_rounded,
                size: _rowIconSize,
                color: AppTheme.settingsLogOut,
              ),
              const SizedBox(width: _controlGap),
              Flexible(
                child: Text(
                  SettingsMessages.logOut,
                  style: SettingsText.label(context)
                      ?.copyWith(color: AppTheme.settingsLogOut),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Label, caption and "?" on top, the control underneath at full width,
/// so the four voice pills and the stepper fit a 320 dp phone.
class _PreferenceRow extends StatelessWidget {
  const _PreferenceRow({
    required this.label,
    required this.caption,
    required this.help,
    required this.control,
    required this.controlGap,
  });

  final String label;
  final String caption;
  final Widget help;

  /// Null until the stored value is read, so the old default never flashes.
  final Widget? control;
  final double controlGap;

  static const double _captionGap = 2;
  // The IconButton's 48 dp box has its own padding; pull it in so the
  // glyph lines up with the row's right inset.
  static const EdgeInsets _padding = EdgeInsets.fromLTRB(16, 8, 4, 16);

  @override
  Widget build(BuildContext context) {
    final control = this.control;
    return Padding(
      padding: _padding,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(label, style: SettingsText.label(context)),
                    const SizedBox(height: _captionGap),
                    Text(caption, style: SettingsText.caption(context)),
                  ],
                ),
              ),
              help,
            ],
          ),
          if (control != null) ...[
            SizedBox(height: controlGap),
            Padding(padding: const EdgeInsets.only(right: 12), child: control),
          ],
        ],
      ),
    );
  }
}

/// The Library header's gradient, mark and title metrics, without the
/// search field or bell, which Settings has no use for.
class _SettingsHeader extends StatelessWidget {
  const _SettingsHeader({required this.horizontalPadding});

  final double horizontalPadding;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    final textScale =
        MediaQuery.textScalerOf(context).scale(LibraryHeader.subtitleFontSize) /
        LibraryHeader.subtitleFontSize;
    final showLogo = textScale <= LibraryHeader.logoMaxTextScale;

    return DecoratedBox(
      decoration: const BoxDecoration(gradient: AppTheme.libraryHeaderGradient),
      child: SafeArea(
        bottom: false,
        child: Padding(
          padding: EdgeInsets.fromLTRB(
            horizontalPadding,
            LibraryHeader.topGap,
            horizontalPadding,
            LibraryHeader.bottomGap,
          ),
          child: Stack(
            children: [
              if (showLogo)
                const Positioned(top: 0, right: 0, child: LibraryHeaderLogo()),
              Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  SizedBox(
                    height: showLogo
                        ? LibraryHeader.titleTop - LibraryHeader.topGap
                        : 0,
                  ),
                  MediaQuery.withClampedTextScaling(
                    maxScaleFactor: LibraryHeader.headingMaxTextScale,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Padding(
                          padding: EdgeInsets.only(
                            right: showLogo
                                ? LibraryHeader.logoMarkWidth +
                                      LibraryHeader.titleToLogoGap
                                : 0,
                          ),
                          child: Semantics(
                            header: true,
                            child: Text(
                              SettingsMessages.title,
                              style: textTheme.headlineLarge?.copyWith(
                                fontSize: LibraryHeader.titleFontSize,
                                fontWeight: FontWeight.w700,
                                height: LibraryHeader.titleLineHeight,
                                color: Colors.white,
                              ),
                            ),
                          ),
                        ),
                        Text(
                          SettingsMessages.subtitle,
                          style: textTheme.bodyLarge?.copyWith(
                            fontSize: LibraryHeader.subtitleFontSize,
                            height: LibraryHeader.subtitleLineHeight,
                            color: Colors.white,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
