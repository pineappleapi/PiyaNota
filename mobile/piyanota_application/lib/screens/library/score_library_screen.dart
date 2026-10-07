import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/score_summary.dart';
import '../../routes/app_routes.dart';
import '../../services/score_library_api.dart';
import '../../state/auth_providers.dart';
import '../../state/score_library_providers.dart';
import '../../theme/app_theme.dart';
import '../../widgets/primary_pill_button.dart';
import '../auth/widgets/auth_error_banner.dart';
import 'library_messages.dart';
import 'widgets/library_bottom_nav.dart';
import 'widgets/library_header.dart';
import 'widgets/score_cards.dart';

/// PIYA-205 — Score Library, the home screen after login.
///
/// It is reached with `pushNamedAndRemoveUntil`, so it is the only route on
/// the stack: Android back exits the app rather than returning to Login.
class ScoreLibraryScreen extends ConsumerStatefulWidget {
  const ScoreLibraryScreen({super.key});

  @override
  ConsumerState<ScoreLibraryScreen> createState() =>
      _ScoreLibraryScreenState();
}

class _ScoreLibraryScreenState extends ConsumerState<ScoreLibraryScreen> {
  final _searchController = TextEditingController();
  String _query = '';

  /// Scores with a delete request in flight. Their rows stay on screen
  /// (PIYA-215 AC2: removed only after the server confirms).
  final Set<int> _deletingIds = {};

  // Mockup: 32 dp side margins at 412 dp wide, header content at 26 dp,
  // first card 32 dp under the header, 18 dp between cards. Margins scale
  // down on narrow phones so cards keep usable text width.
  static const double _cardMarginFraction = 32 / 412;
  static const double _maxCardMargin = 32;
  static const double _minCardMargin = 16;
  static const double _headerInsetFromCards = 6;
  static const double _listTopGap = 32;
  static const double _cardGap = 18;
  static const double _stateMessageTopGap = 16;
  static const double _snackBarSideMargin = 16;

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  /// AC3: filters on every keystroke. PIYA-215 AC1 adds the debounce and a
  /// PIYA-308 call here; the screen only ever renders the filtered result.
  void _onSearchChanged(String value) => setState(() => _query = value);

  void _openScore(ScoreSummary score) {
    // AC7: the existing score's id only — Playback loads its stored audio;
    // nothing here triggers processing.
    Navigator.of(context).pushNamed(
      AppRoutes.playback,
      arguments: PlaybackArguments(scoreId: score.scoreId, title: score.title),
    );
  }

  void _openCapture() => Navigator.of(context).pushNamed(AppRoutes.capture);

  void _openSettings() => Navigator.of(context).pushNamed(AppRoutes.settings);

  Future<void> _returnToLogin() async {
    try {
      await ref.read(sessionStorageProvider).clear();
    } catch (e) {
      // The token is already rejected by the server; failing to wipe it
      // locally must not trap the user on this screen.
      debugPrint('Session clear failed: $e');
    }
    if (!mounted) return;
    Navigator.of(context).pushNamedAndRemoveUntil(AppRoutes.login, (_) => false);
  }

  Future<void> _confirmDelete(ScoreSummary score) async {
    // PIYA-309 AC5: the API deletes without asking, so confirmation is ours.
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => _DeleteScoreDialog(title: score.title),
    );
    if (confirmed != true || !mounted) return;

    setState(() => _deletingIds.add(score.scoreId));
    String message;
    try {
      await ref.read(scoreLibraryProvider.notifier).delete(score.scoreId);
      message = LibraryMessages.deleted(score.title);
    } on ScoreNotFoundException {
      message = LibraryMessages.deleteAlreadyGone;
    } on SessionExpiredException {
      message = LibraryMessages.sessionExpired;
    } on ScoreLibraryNetworkException {
      message = LibraryMessages.deleteNetworkError;
    } catch (e, stack) {
      // Anything unmapped still has to clear the row's spinner.
      debugPrint('Score delete failed: $e\n$stack');
      message = LibraryMessages.deleteServerError;
    }
    if (!mounted) return;
    setState(() => _deletingIds.remove(score.scoreId));
    _showSnackBar(message);
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
          // Floats above the custom nav bar, which lives in the body and so
          // isn't known to Scaffold's own snackbar placement.
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
    final library = ref.watch(scoreLibraryProvider);
    final width = MediaQuery.sizeOf(context).width;
    final cardMargin = (width * _cardMarginFraction)
        .clamp(_minCardMargin, _maxCardMargin)
        .toDouble();
    final navHeight = LibraryBottomNav.heightFor(
      MediaQuery.paddingOf(context).bottom,
    );
    final keyboardHeight = MediaQuery.viewInsetsOf(context).bottom;

    final subtitle = switch (library) {
      AsyncData(:final value) => value.isEmpty
          ? LibraryMessages.emptySubtitle
          : LibraryMessages.scoreCountSubtitle(value.length),
      AsyncError() => LibraryMessages.errorSubtitle,
      _ => LibraryMessages.loadingSubtitle,
    };

    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: SystemUiOverlayStyle.light,
      child: Scaffold(
        backgroundColor: AppTheme.libraryBackground,
        // The nav bar stays put behind the keyboard; the list pads by the
        // keyboard height instead so every result is still reachable.
        resizeToAvoidBottomInset: false,
        body: Stack(
          children: [
            Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                LibraryHeader(
                  subtitle: subtitle,
                  searchController: _searchController,
                  onSearchChanged: _onSearchChanged,
                  horizontalPadding: cardMargin - _headerInsetFromCards,
                ),
                Expanded(
                  child: ListView(
                    keyboardDismissBehavior:
                        ScrollViewKeyboardDismissBehavior.onDrag,
                    padding: EdgeInsets.fromLTRB(
                      cardMargin,
                      _listTopGap,
                      cardMargin,
                      (keyboardHeight > navHeight ? keyboardHeight : navHeight) +
                          _cardGap,
                    ),
                    children: [
                      AddScoreCard(onTap: _openCapture),
                      ..._buildStateContent(library),
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
                // Library is this screen.
                onLibrary: () {},
                onCapture: _openCapture,
                onSettings: _openSettings,
              ),
            ),
          ],
        ),
      ),
    );
  }

  List<Widget> _buildStateContent(AsyncValue<List<ScoreSummary>> library) {
    switch (library) {
      case AsyncData(:final value):
        // AC4: zero scores shows only the Add Score card, as in the mockup;
        // the header subtitle carries the empty-state message.
        if (value.isEmpty) return const [];
        final visible = filterScoresByTitle(value, _query);
        if (visible.isEmpty) {
          return [
            const SizedBox(height: _cardGap + _stateMessageTopGap),
            _NoMatchesMessage(query: _query),
          ];
        }
        return [
          for (final score in visible) ...[
            const SizedBox(height: _cardGap),
            ScoreCard(
              key: ValueKey(score.scoreId),
              score: score,
              isDeleting: _deletingIds.contains(score.scoreId),
              onTap: () => _openScore(score),
              onDelete: () => _confirmDelete(score),
            ),
          ],
        ];
      case AsyncError(:final error):
        final sessionExpired = error is SessionExpiredException;
        return [
          const SizedBox(height: _cardGap),
          _LoadErrorPanel(
            message: _loadErrorMessage(error),
            actionLabel: sessionExpired
                ? LibraryMessages.logInAgain
                : LibraryMessages.retry,
            onAction: sessionExpired
                ? _returnToLogin
                : () => ref.read(scoreLibraryProvider.notifier).reload(),
          ),
        ];
      default:
        return const [
          SizedBox(height: _cardGap),
          _LoadingSkeletons(),
        ];
    }
  }

  static String _loadErrorMessage(Object error) => switch (error) {
        SessionExpiredException() => LibraryMessages.sessionExpired,
        ScoreLibraryNetworkException() => LibraryMessages.loadNetworkError,
        _ => LibraryMessages.loadServerError,
      };
}

class _LoadingSkeletons extends StatelessWidget {
  const _LoadingSkeletons();

  static const int _count = 3;
  static const double _gap = 18;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      key: const Key('library-loading'),
      label: LibraryMessages.loadingSemantics,
      liveRegion: true,
      container: true,
      excludeSemantics: true,
      child: Column(
        children: [
          for (var i = 0; i < _count; i++) ...[
            if (i > 0) const SizedBox(height: _gap),
            const ScoreCardSkeleton(),
          ],
        ],
      ),
    );
  }
}

/// AC6 error state, reusing the auth screens' banner and pill button so
/// failures look the same across the app.
class _LoadErrorPanel extends StatelessWidget {
  const _LoadErrorPanel({
    required this.message,
    required this.actionLabel,
    required this.onAction,
  });

  final String message;
  final String actionLabel;
  final VoidCallback onAction;

  static const double _gap = 16;

  @override
  Widget build(BuildContext context) {
    return Column(
      key: const Key('library-error'),
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        AuthErrorBanner(message: message),
        const SizedBox(height: _gap),
        PrimaryPillButton(label: actionLabel, onPressed: onAction),
      ],
    );
  }
}

/// Search returned nothing although the library isn't empty — kept visibly
/// different from the AC4 empty state, which tells the user to capture.
class _NoMatchesMessage extends StatelessWidget {
  const _NoMatchesMessage({required this.query});

  final String query;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      liveRegion: true,
      child: Text(
        LibraryMessages.noMatches(query),
        textAlign: TextAlign.center,
        style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: AppTheme.libraryScoreSubtitle,
            ),
      ),
    );
  }
}

class _DeleteScoreDialog extends StatelessWidget {
  const _DeleteScoreDialog({required this.title});

  final String title;

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      backgroundColor: Colors.white,
      title: const Text(LibraryMessages.deleteDialogTitle),
      content: Text(LibraryMessages.deleteDialogBody(title)),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(false),
          style: TextButton.styleFrom(
            foregroundColor: AppTheme.libraryScoreSubtitle,
          ),
          child: const Text(LibraryMessages.deleteCancel),
        ),
        TextButton(
          onPressed: () => Navigator.of(context).pop(true),
          style: TextButton.styleFrom(foregroundColor: AppTheme.errorRed),
          child: const Text(LibraryMessages.deleteConfirm),
        ),
      ],
    );
  }
}
