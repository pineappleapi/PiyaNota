import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:piyanota_application/models/score_summary.dart';
import 'package:piyanota_application/routes/app_routes.dart';
import 'package:piyanota_application/screens/library/library_messages.dart';
import 'package:piyanota_application/screens/library/score_library_screen.dart';
import 'package:piyanota_application/screens/library/widgets/library_bottom_nav.dart';
import 'package:piyanota_application/screens/library/widgets/library_header.dart';
import 'package:piyanota_application/screens/library/widgets/score_cards.dart';
import 'package:piyanota_application/services/score_library_api.dart';
import 'package:piyanota_application/state/score_library_providers.dart';
import 'package:piyanota_application/theme/app_theme.dart';

/// [ScoreLibraryApi] whose every call is answered by the test, either
/// immediately or via a [Completer] so in-flight states are observable.
class ScriptedScoreLibraryApi implements ScoreLibraryApi {
  ScriptedScoreLibraryApi({required this.onFetch, this.onDelete});

  Future<List<ScoreSummary>> Function() onFetch;
  Future<void> Function(int scoreId)? onDelete;
  Future<void> Function(int scoreId)? onRecordOpened;
  int fetchCalls = 0;
  final List<int> deletedIds = [];
  final List<int> openedIds = [];

  @override
  Future<List<ScoreSummary>> fetchLibrary({String? query}) {
    fetchCalls++;
    return onFetch();
  }

  @override
  Future<void> deleteScore(int scoreId) {
    deletedIds.add(scoreId);
    return onDelete!(scoreId);
  }

  @override
  Future<void> recordOpened(int scoreId) async {
    openedIds.add(scoreId);
    await onRecordOpened?.call(scoreId);
  }
}

/// The card list's own Scrollable (the search field has one too).
final _libraryScrollable = find
    .descendant(of: find.byType(ListView), matching: find.byType(Scrollable))
    .first;

/// Steps the card list's scroll position until [target] is built. Moves
/// the position directly: at 2x text on 320x568 the bottom nav covers the
/// list's centre, where a drag gesture would land.
Future<void> _scrollListUntilBuilt(WidgetTester tester, Finder target) async {
  const step = 100.0;
  final position = tester.state<ScrollableState>(_libraryScrollable).position;
  while (target.evaluate().isEmpty &&
      position.pixels < position.maxScrollExtent) {
    position.jumpTo(
      (position.pixels + step).clamp(0.0, position.maxScrollExtent),
    );
    await tester.pump();
  }
}

final _scores = [
  ScoreSummary(
    scoreId: 101,
    title: 'Bituin Walang Ningning',
    lastActivityAt: DateTime(2026, 10, 3, 12),
    composer: 'Robert Delgado',
    pageCount: 10,
  ),
  ScoreSummary(
    scoreId: 102,
    title: 'Paraiso',
    lastActivityAt: DateTime(2026, 9, 28, 12),
  ),
  ScoreSummary(
    scoreId: 103,
    title: 'Bahay Kubo',
    lastActivityAt: DateTime(2026, 9, 21, 12),
    pageCount: 7,
  ),
];

const _playbackMarker = 'ROUTE:playback';
const _captureMarker = 'ROUTE:capture';
const _settingsMarker = 'ROUTE:settings';
const _loginMarker = 'ROUTE:login';

/// Arguments the stub Playback route received, for AC7.
Object? _lastPlaybackArguments;

Future<void> _pumpLibrary(
  WidgetTester tester,
  ScoreLibraryApi api, {
  Size physicalSize = const Size(1080, 2340),
  double devicePixelRatio = 2.75,
  double textScale = 1.0,
  double topInset = 0,
  bool disableAnimations = false,
}) async {
  FlutterSecureStorage.setMockInitialValues({});
  _lastPlaybackArguments = null;
  tester.view.physicalSize = physicalSize;
  tester.view.devicePixelRatio = devicePixelRatio;
  tester.view.padding = FakeViewPadding(top: topInset * devicePixelRatio);
  addTearDown(tester.view.reset);

  await tester.pumpWidget(
    ProviderScope(
      overrides: [scoreLibraryApiProvider.overrideWithValue(api)],
      child: MaterialApp(
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(context).copyWith(
            textScaler: TextScaler.linear(textScale),
            disableAnimations: disableAnimations,
          ),
          child: child!,
        ),
        home: const ScoreLibraryScreen(),
        routes: {
          AppRoutes.playback: (context) {
            _lastPlaybackArguments = ModalRoute.of(context)?.settings.arguments;
            return const Scaffold(body: Text(_playbackMarker));
          },
          AppRoutes.capture: (_) => const Scaffold(body: Text(_captureMarker)),
          AppRoutes.settings: (_) =>
              const Scaffold(body: Text(_settingsMarker)),
          AppRoutes.login: (_) => const Scaffold(body: Text(_loginMarker)),
        },
      ),
    ),
  );
}

ScriptedScoreLibraryApi _apiReturning(List<ScoreSummary> scores) =>
    ScriptedScoreLibraryApi(onFetch: () async => [...scores]);

Finder _deleteButtonFor(String title) =>
    find.bySemanticsLabel(LibraryMessages.deleteSemantics(title));

Future<void> _tapDelete(WidgetTester tester, String title) async {
  await tester.tap(
    find.descendant(
      of: find
          .ancestor(of: find.text(title), matching: find.byType(Material))
          .first,
      matching: find.byIcon(Icons.delete_rounded),
    ),
  );
  await tester.pumpAndSettle();
}

/// Titles of the visible score cards, top to bottom.
List<String> _visibleTitleOrder(WidgetTester tester) {
  final cards = find.byType(ScoreCard).evaluate().toList()
    ..sort(
      (a, b) => tester
          .getTopLeft(find.byWidget(a.widget))
          .dy
          .compareTo(tester.getTopLeft(find.byWidget(b.widget)).dy),
    );
  return [
    for (final card in cards) (card.widget as ScoreCard).entry.displayTitle,
  ];
}

void main() {
  group('AC5 loading', () {
    testWidgets('shows skeletons and a loading subtitle while fetching', (
      tester,
    ) async {
      final pending = Completer<List<ScoreSummary>>();
      await _pumpLibrary(
        tester,
        ScriptedScoreLibraryApi(onFetch: () => pending.future),
      );
      await tester.pump();

      expect(find.byKey(const Key('library-loading')), findsOneWidget);
      expect(find.text(LibraryMessages.loadingSubtitle), findsOneWidget);
      // Header, search and nav stay usable during the load.
      expect(find.text(LibraryMessages.title), findsOneWidget);
      expect(find.byType(TextField), findsOneWidget);
      expect(find.text('Capture'), findsOneWidget);

      pending.complete(_scores);
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('library-loading')), findsNothing);
    });
  });

  group('AC6 error + retry', () {
    testWidgets('server failure shows an error with Retry that refetches', (
      tester,
    ) async {
      var fail = true;
      final api = ScriptedScoreLibraryApi(
        onFetch: () async {
          if (fail) throw const ScoreLibraryServerException();
          return _scores;
        },
      );
      await _pumpLibrary(tester, api);
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('library-error')), findsOneWidget);
      expect(find.text(LibraryMessages.loadServerError), findsOneWidget);
      expect(find.text(LibraryMessages.errorSubtitle), findsOneWidget);
      // No silent automatic retry loop (Riverpod 3 default disabled).
      await tester.pump(const Duration(seconds: 5));
      expect(api.fetchCalls, 1);

      fail = false;
      await tester.tap(find.text(LibraryMessages.retry));
      await tester.pumpAndSettle();

      expect(api.fetchCalls, 2);
      expect(find.byKey(const Key('library-error')), findsNothing);
      expect(find.text('Paraiso'), findsOneWidget);
    });

    testWidgets('Retry shows the loading state while the refetch runs', (
      tester,
    ) async {
      var attempt = 0;
      final second = Completer<List<ScoreSummary>>();
      await _pumpLibrary(
        tester,
        ScriptedScoreLibraryApi(
          onFetch: () {
            attempt++;
            if (attempt == 1) {
              return Future.error(const ScoreLibraryServerException());
            }
            return second.future;
          },
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text(LibraryMessages.retry));
      await tester.pump();

      expect(find.byKey(const Key('library-loading')), findsOneWidget);
      expect(find.byKey(const Key('library-error')), findsNothing);
      second.complete(_scores);
      await tester.pumpAndSettle();
    });

    testWidgets('network failure says to check the connection', (tester) async {
      await _pumpLibrary(
        tester,
        ScriptedScoreLibraryApi(
          onFetch: () async => throw const ScoreLibraryNetworkException(),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text(LibraryMessages.loadNetworkError), findsOneWidget);
    });

    testWidgets('an unexpected exception still ends in the error state', (
      tester,
    ) async {
      await _pumpLibrary(
        tester,
        ScriptedScoreLibraryApi(onFetch: () async => throw StateError('x')),
      );
      await tester.pumpAndSettle();
      expect(find.text(LibraryMessages.loadServerError), findsOneWidget);
    });

    testWidgets('401 offers Log In instead of Retry and returns to Login', (
      tester,
    ) async {
      await _pumpLibrary(
        tester,
        ScriptedScoreLibraryApi(
          onFetch: () async => throw const SessionExpiredException(),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text(LibraryMessages.sessionExpired), findsOneWidget);
      expect(find.text(LibraryMessages.retry), findsNothing);
      await tester.tap(find.text(LibraryMessages.logInAgain));
      await tester.pumpAndSettle();
      expect(find.text(_loginMarker), findsOneWidget);
    });
  });

  group('AC4 empty', () {
    testWidgets('zero scores shows the mockup empty subtitle and Add Score', (
      tester,
    ) async {
      await _pumpLibrary(tester, _apiReturning(const []));
      await tester.pumpAndSettle();

      expect(find.text('No Scores • Tap Capture Button'), findsOneWidget);
      expect(find.text(LibraryMessages.addScoreTitle), findsOneWidget);
      expect(find.byIcon(Icons.delete_rounded), findsNothing);
    });
  });

  group('AC2 list', () {
    testWidgets('each entry shows its title and last-activity date', (
      tester,
    ) async {
      await _pumpLibrary(tester, _apiReturning(_scores));
      await tester.pumpAndSettle();

      expect(find.text('3 Scores • Tap to Listen'), findsOneWidget);
      expect(find.text('Bituin Walang Ningning'), findsOneWidget);
      expect(
        find.text('Oct 3, 2026 • Robert Delgado • 10 pages'),
        findsOneWidget,
      );
      expect(find.text('Sep 28, 2026'), findsOneWidget);
      expect(find.text('Sep 21, 2026 • 7 pages'), findsOneWidget);
    });

    testWidgets('one score uses the singular subtitle', (tester) async {
      await _pumpLibrary(tester, _apiReturning(_scores.take(1).toList()));
      await tester.pumpAndSettle();
      expect(find.text('1 Score • Tap to Listen'), findsOneWidget);
    });
  });

  group('AC3 search', () {
    testWidgets('filters case-insensitively by partial title as you type', (
      tester,
    ) async {
      await _pumpLibrary(tester, _apiReturning(_scores));
      await tester.pumpAndSettle();

      await tester.enterText(find.byType(TextField), 'B');
      await tester.pump();
      expect(find.text('Bituin Walang Ningning'), findsOneWidget);
      expect(find.text('Bahay Kubo'), findsOneWidget);
      expect(find.text('Paraiso'), findsNothing);

      await tester.enterText(find.byType(TextField), 'kUb');
      await tester.pump();
      expect(find.text('Bahay Kubo'), findsOneWidget);
      expect(find.text('Bituin Walang Ningning'), findsNothing);

      await tester.enterText(find.byType(TextField), '  ningning ');
      await tester.pump();
      expect(find.text('Bituin Walang Ningning'), findsOneWidget);
      expect(find.text('Bahay Kubo'), findsNothing);

      await tester.enterText(find.byType(TextField), '');
      await tester.pump();
      expect(find.byIcon(Icons.delete_rounded), findsNWidgets(3));
    });

    testWidgets('zero matches shows a distinct message, not the empty state', (
      tester,
    ) async {
      await _pumpLibrary(tester, _apiReturning(_scores));
      await tester.pumpAndSettle();

      await tester.enterText(find.byType(TextField), 'zzz');
      await tester.pump();

      expect(find.text(LibraryMessages.noResultsTitle), findsOneWidget);
      expect(
        find.text('Nothing matches "zzz". Try a title, composer or date.'),
        findsOneWidget,
      );
      expect(find.text(LibraryMessages.emptySubtitle), findsNothing);
      // The subtitle keeps describing the whole library.
      expect(find.text('3 Scores • Tap to Listen'), findsOneWidget);
    });
  });

  group('AC7 / AC8 navigation', () {
    testWidgets('tapping a score opens Playback with its scoreId', (
      tester,
    ) async {
      final api = _apiReturning(_scores);
      await _pumpLibrary(tester, api);
      await tester.pumpAndSettle();

      await tester.tap(find.text('Paraiso'));
      await tester.pumpAndSettle();

      expect(find.text(_playbackMarker), findsOneWidget);
      expect(_lastPlaybackArguments, isA<PlaybackArguments>());
      final arguments = _lastPlaybackArguments! as PlaybackArguments;
      expect(arguments.scoreId, 102);
      expect(arguments.title, 'Paraiso');
      // Nothing re-fetched or re-processed on the way.
      expect(api.fetchCalls, 1);
    });

    testWidgets('Add Score card routes to Capture', (tester) async {
      await _pumpLibrary(tester, _apiReturning(_scores));
      await tester.pumpAndSettle();
      await tester.tap(find.text(LibraryMessages.addScoreTitle));
      await tester.pumpAndSettle();
      expect(find.text(_captureMarker), findsOneWidget);
    });

    testWidgets('nav Capture button routes to Capture', (tester) async {
      await _pumpLibrary(tester, _apiReturning(_scores));
      await tester.pumpAndSettle();
      await tester.tap(find.bySemanticsLabel('Capture'));
      await tester.pumpAndSettle();
      expect(find.text(_captureMarker), findsOneWidget);
    });

    testWidgets('raised part of the Capture button is tappable', (
      tester,
    ) async {
      await _pumpLibrary(tester, _apiReturning(_scores));
      await tester.pumpAndSettle();
      final glyph = tester.getCenter(find.byIcon(Icons.crop_free_rounded));
      // Top of the ellipse, above the gradient bar.
      await tester.tapAt(glyph.translate(0, -24));
      await tester.pumpAndSettle();
      expect(find.text(_captureMarker), findsOneWidget);
    });

    testWidgets('nav Settings routes to Settings', (tester) async {
      await _pumpLibrary(tester, _apiReturning(_scores));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Settings'));
      await tester.pumpAndSettle();
      expect(find.text(_settingsMarker), findsOneWidget);
    });

    testWidgets('Capture is reachable from the empty and error states', (
      tester,
    ) async {
      await _pumpLibrary(
        tester,
        ScriptedScoreLibraryApi(
          onFetch: () async => throw const ScoreLibraryServerException(),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text(LibraryMessages.addScoreTitle));
      await tester.pumpAndSettle();
      expect(find.text(_captureMarker), findsOneWidget);
    });
  });

  group('delete (PIYA-215 AC2, PIYA-309)', () {
    testWidgets('trash asks for confirmation and never opens Playback', (
      tester,
    ) async {
      final api = _apiReturning(_scores)..onDelete = (_) async {};
      await _pumpLibrary(tester, api);
      await tester.pumpAndSettle();

      await _tapDelete(tester, 'Paraiso');

      expect(find.text(LibraryMessages.deleteDialogTitle), findsOneWidget);
      expect(find.text(_playbackMarker), findsNothing);
      expect(api.deletedIds, isEmpty);
    });

    testWidgets('cancel leaves the score and sends nothing', (tester) async {
      final api = _apiReturning(_scores)..onDelete = (_) async {};
      await _pumpLibrary(tester, api);
      await tester.pumpAndSettle();

      await _tapDelete(tester, 'Paraiso');
      await tester.tap(find.text(LibraryMessages.deleteCancel));
      await tester.pumpAndSettle();

      expect(api.deletedIds, isEmpty);
      expect(find.text('Paraiso'), findsOneWidget);
    });

    testWidgets('confirm keeps the row until the server says 200', (
      tester,
    ) async {
      final server = Completer<void>();
      final api = _apiReturning(_scores)..onDelete = (_) => server.future;
      await _pumpLibrary(tester, api);
      await tester.pumpAndSettle();

      await _tapDelete(tester, 'Paraiso');
      await tester.tap(find.text(LibraryMessages.deleteConfirm));
      await tester.pump();

      expect(api.deletedIds, [102]);
      expect(find.text('Paraiso'), findsOneWidget, reason: 'not optimistic');
      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      // The deleting row can't be opened.
      await tester.tap(find.text('Paraiso'));
      await tester.pump();
      expect(find.text(_playbackMarker), findsNothing);

      server.complete();
      await tester.pumpAndSettle();

      expect(find.text('Paraiso'), findsNothing);
      expect(find.text(LibraryMessages.deleted('Paraiso')), findsOneWidget);
      expect(find.text('2 Scores • Tap to Listen'), findsOneWidget);
    });

    testWidgets('server failure keeps the row and shows an error', (
      tester,
    ) async {
      final api = _apiReturning(_scores)
        ..onDelete = (_) async => throw const ScoreLibraryServerException();
      await _pumpLibrary(tester, api);
      await tester.pumpAndSettle();

      await _tapDelete(tester, 'Paraiso');
      await tester.tap(find.text(LibraryMessages.deleteConfirm));
      await tester.pumpAndSettle();

      expect(find.text('Paraiso'), findsOneWidget);
      expect(find.text(LibraryMessages.deleteServerError), findsOneWidget);
      expect(find.byType(CircularProgressIndicator), findsNothing);
      expect(find.text('3 Scores • Tap to Listen'), findsOneWidget);
    });

    testWidgets('network failure keeps the row with a connection message', (
      tester,
    ) async {
      final api = _apiReturning(_scores)
        ..onDelete = (_) async => throw const ScoreLibraryNetworkException();
      await _pumpLibrary(tester, api);
      await tester.pumpAndSettle();

      await _tapDelete(tester, 'Paraiso');
      await tester.tap(find.text(LibraryMessages.deleteConfirm));
      await tester.pumpAndSettle();

      expect(find.text('Paraiso'), findsOneWidget);
      expect(find.text(LibraryMessages.deleteNetworkError), findsOneWidget);
    });

    testWidgets('404 removes the row and says it was already gone', (
      tester,
    ) async {
      final api = _apiReturning(_scores)
        ..onDelete = (_) async => throw const ScoreNotFoundException();
      await _pumpLibrary(tester, api);
      await tester.pumpAndSettle();

      await _tapDelete(tester, 'Paraiso');
      await tester.tap(find.text(LibraryMessages.deleteConfirm));
      await tester.pumpAndSettle();

      expect(find.text('Paraiso'), findsNothing);
      expect(find.text(LibraryMessages.deleteAlreadyGone), findsOneWidget);
    });

    testWidgets('trash exposes an accessible "Delete <title>" action', (
      tester,
    ) async {
      final handle = tester.ensureSemantics();
      await _pumpLibrary(tester, _apiReturning(_scores));
      await tester.pumpAndSettle();
      expect(_deleteButtonFor('Paraiso'), findsOneWidget);
      handle.dispose();
    });
  });

  group('sort by last opened', () {
    testWidgets('newest opened first, whatever order the server sends', (
      tester,
    ) async {
      await _pumpLibrary(
        tester,
        _apiReturning([_scores[2], _scores[0], _scores[1]]),
      );
      await tester.pumpAndSettle();
      expect(_visibleTitleOrder(tester), [
        'Bituin Walang Ningning',
        'Paraiso',
        'Bahay Kubo',
      ]);
    });

    testWidgets('opening a score bumps it to the top', (tester) async {
      await _pumpLibrary(tester, _apiReturning(_scores));
      await tester.pumpAndSettle();

      await tester.tap(find.text('Bahay Kubo'));
      await tester.pumpAndSettle();
      expect(find.text(_playbackMarker), findsOneWidget);
      Navigator.of(tester.element(find.text(_playbackMarker))).pop();
      await tester.pumpAndSettle();

      expect(_visibleTitleOrder(tester), [
        'Bahay Kubo',
        'Bituin Walang Ningning',
        'Paraiso',
      ]);
    });
  });

  group('broken entries', () {
    testWidgets('untitled scores read "New Score", numbered by scoreId', (
      tester,
    ) async {
      await _pumpLibrary(
        tester,
        _apiReturning([
          ScoreSummary(scoreId: 1, lastActivityAt: DateTime(2026, 10, 5, 12)),
          ScoreSummary(
            scoreId: 2,
            title: 'New Score',
            lastActivityAt: DateTime(2026, 10, 4, 12),
          ),
          const ScoreSummary(scoreId: 3, composer: 'Ryan Cayabyab'),
          ScoreSummary(
            scoreId: 4,
            title: 'Paraiso',
            lastActivityAt: DateTime(2026, 10, 1, 12),
          ),
        ]),
      );
      await tester.pumpAndSettle();

      expect(_visibleTitleOrder(tester), [
        'New Score',
        'New Score (1)',
        'Paraiso',
        'New Score (2)',
      ]);
      // No date and no pages: just the composer, no stray separator.
      expect(find.text('Ryan Cayabyab'), findsOneWidget);
      expect(
        find.textContaining('•'),
        findsOneWidget,
        reason: 'only the header subtitle uses a separator',
      );

      await tester.enterText(find.byType(TextField), 'new score');
      await tester.pump();
      expect(find.text('Paraiso'), findsNothing);
      expect(find.text('New Score (2)'), findsOneWidget);
    });

    testWidgets('a score with no subtitle parts shows no subtitle line', (
      tester,
    ) async {
      await _pumpLibrary(
        tester,
        _apiReturning([const ScoreSummary(scoreId: 9, title: 'Bare')]),
      );
      await tester.pumpAndSettle();
      final card = find.ancestor(
        of: find.text('Bare'),
        matching: find.byType(ScoreCard),
      );
      expect(
        find.descendant(of: card, matching: find.byType(Text)),
        findsOneWidget,
      );
    });
  });

  group('wider search', () {
    testWidgets('matches composer and the displayed date', (tester) async {
      await _pumpLibrary(tester, _apiReturning(_scores));
      await tester.pumpAndSettle();

      await tester.enterText(find.byType(TextField), 'DELGADO');
      await tester.pump();
      expect(_visibleTitleOrder(tester), ['Bituin Walang Ningning']);

      await tester.enterText(find.byType(TextField), 'sep 28');
      await tester.pump();
      expect(_visibleTitleOrder(tester), ['Paraiso']);

      await tester.enterText(find.byType(TextField), 'Sep');
      await tester.pump();
      expect(_visibleTitleOrder(tester), ['Paraiso', 'Bahay Kubo']);

      await tester.enterText(find.byType(TextField), '2026');
      await tester.pump();
      expect(_visibleTitleOrder(tester), [
        'Bituin Walang Ningning',
        'Paraiso',
        'Bahay Kubo',
      ]);
    });

    testWidgets('clear button resets the filter and keeps focus', (
      tester,
    ) async {
      await _pumpLibrary(tester, _apiReturning(_scores));
      await tester.pumpAndSettle();
      final clear = find.byKey(const ValueKey('library-search-clear'));
      expect(clear, findsNothing);

      await tester.enterText(find.byType(TextField), 'kubo');
      await tester.pump();
      expect(_visibleTitleOrder(tester), ['Bahay Kubo']);
      expect(clear, findsOneWidget);

      await tester.tap(clear);
      await tester.pump();

      expect(clear, findsNothing);
      final field = tester.widget<EditableText>(find.byType(EditableText));
      expect(field.controller.text, isEmpty);
      expect(field.focusNode.hasFocus, isTrue);
      expect(_visibleTitleOrder(tester), hasLength(3));
    });
  });

  group('swipe to delete', () {
    Future<void> swipe(WidgetTester tester, String title) async {
      await tester.drag(find.text(title), const Offset(-600, 0));
      await tester.pumpAndSettle();
    }

    testWidgets('cancel snaps the row back and sends nothing', (tester) async {
      final api = _apiReturning(_scores)..onDelete = (_) async {};
      await _pumpLibrary(tester, api);
      await tester.pumpAndSettle();

      await swipe(tester, 'Paraiso');
      expect(find.text(LibraryMessages.deleteDialogTitle), findsOneWidget);
      await tester.tap(find.text(LibraryMessages.deleteCancel));
      await tester.pumpAndSettle();

      expect(api.deletedIds, isEmpty);
      expect(find.text('Paraiso'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('confirm removes the row only after the server says 200', (
      tester,
    ) async {
      final server = Completer<void>();
      final api = _apiReturning(_scores)..onDelete = (_) => server.future;
      await _pumpLibrary(tester, api);
      await tester.pumpAndSettle();

      await swipe(tester, 'Paraiso');
      await tester.tap(find.text(LibraryMessages.deleteConfirm));
      // The row's spinner runs until the server answers, so the tree never
      // settles here; pump past the dialog's exit instead.
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));

      expect(api.deletedIds, [102]);
      expect(find.text('Paraiso'), findsOneWidget, reason: 'not optimistic');

      server.complete();
      await tester.pumpAndSettle();
      expect(find.text('Paraiso'), findsNothing);
      expect(find.text(LibraryMessages.deleted('Paraiso')), findsOneWidget);
      expect(find.text('2 Scores • Tap to Listen'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('server failure snaps the row back with the error', (
      tester,
    ) async {
      final api = _apiReturning(_scores)
        ..onDelete = (_) async => throw const ScoreLibraryServerException();
      await _pumpLibrary(tester, api);
      await tester.pumpAndSettle();

      await swipe(tester, 'Paraiso');
      await tester.tap(find.text(LibraryMessages.deleteConfirm));
      await tester.pumpAndSettle();

      expect(find.text('Paraiso'), findsOneWidget);
      // Back in place, not left slid off-screen.
      expect(
        tester.getTopLeft(find.text('Paraiso')).dx,
        tester.getTopLeft(find.text('Bahay Kubo')).dx,
      );
      expect(find.text(LibraryMessages.deleteServerError), findsOneWidget);
      expect(find.text('3 Scores • Tap to Listen'), findsOneWidget);
    });
  });

  group('header, nav and motion polish', () {
    testWidgets('logo sits top-right, faded, clear of the safe area', (
      tester,
    ) async {
      const statusBar = 24.0;
      await _pumpLibrary(tester, _apiReturning(_scores), topInset: statusBar);
      await tester.pumpAndSettle();

      final logo = find.byKey(const ValueKey('library-header-logo'));
      final rect = tester.getRect(logo);
      final screenWidth =
          tester.view.physicalSize.width / tester.view.devicePixelRatio;
      expect(rect.top, greaterThanOrEqualTo(statusBar + 8));
      expect(rect.left, greaterThan(screenWidth / 2));
      // Right edge lines up with the search field's.
      expect(
        rect.right,
        closeTo(tester.getRect(find.byType(TextField)).right, 0.5),
      );

      final opacity = tester.widget<Opacity>(
        find.descendant(of: logo, matching: find.byType(Opacity)),
      );
      expect(opacity.opacity, AppTheme.libraryHeaderLogoOpacity);
      expect(opacity.opacity, inInclusiveRange(0.35, 0.45));
      // Title shares the logo's band rather than sitting under it.
      expect(
        tester.getRect(find.text(LibraryMessages.title)).top,
        lessThan(rect.bottom),
      );
    });

    testWidgets('Capture is a true circle; Library shows as selected', (
      tester,
    ) async {
      await _pumpLibrary(tester, _apiReturning(_scores));
      await tester.pumpAndSettle();

      final capture = tester.getSize(
        find.byKey(const ValueKey('library-capture-button')),
      );
      expect(capture.width, capture.height);

      final indicator = find.byKey(
        const ValueKey('library-nav-selected-indicator'),
      );
      expect(indicator, findsOneWidget);
      expect(
        tester.getCenter(indicator).dx,
        closeTo(tester.getCenter(find.text('Library')).dx, 0.5),
      );
    });

    testWidgets('skeleton shimmer runs, then stops so the screen settles', (
      tester,
    ) async {
      final pending = Completer<List<ScoreSummary>>();
      await _pumpLibrary(
        tester,
        ScriptedScoreLibraryApi(onFetch: () => pending.future),
      );
      await tester.pump();
      final skeleton = find.byType(ScoreCardSkeleton).first;
      expect(
        tester.state<ScoreCardSkeletonState>(skeleton).isShimmering,
        isTrue,
      );

      await tester.pumpAndSettle();
      expect(find.byKey(const Key('library-loading')), findsOneWidget);
      expect(
        tester.state<ScoreCardSkeletonState>(skeleton).isShimmering,
        isFalse,
      );
      pending.complete(_scores);
      await tester.pumpAndSettle();
    });

    testWidgets('reduce motion: no shimmer, deleted rows leave at once', (
      tester,
    ) async {
      final pending = Completer<List<ScoreSummary>>();
      final api = ScriptedScoreLibraryApi(
        onFetch: () => pending.future,
        onDelete: (_) async {},
      );
      await _pumpLibrary(tester, api, disableAnimations: true);
      await tester.pump();
      expect(
        tester
            .state<ScoreCardSkeletonState>(find.byType(ScoreCardSkeleton).first)
            .isShimmering,
        isFalse,
      );
      expect(tester.hasRunningAnimations, isFalse);

      pending.complete(_scores);
      await tester.pumpAndSettle();
      await _tapDelete(tester, 'Paraiso');
      await tester.tap(find.text(LibraryMessages.deleteConfirm));
      // Zero-duration pumps only: no exit animation to wait for.
      await tester.pump();
      await tester.pump();
      await tester.pump();
      expect(find.text('Paraiso'), findsNothing);
    });

    testWidgets('with motion, a trash-deleted row fades out before leaving', (
      tester,
    ) async {
      final api = _apiReturning(_scores)..onDelete = (_) async {};
      await _pumpLibrary(tester, api);
      await tester.pumpAndSettle();

      await _tapDelete(tester, 'Paraiso');
      await tester.tap(find.text(LibraryMessages.deleteConfirm));
      await tester.pump();
      await tester.pump();
      await tester.pump();
      expect(find.text('Paraiso'), findsOneWidget, reason: 'still animating');

      await tester.pumpAndSettle();
      expect(find.text('Paraiso'), findsNothing);
      expect(tester.takeException(), isNull);
    });
  });

  group('NFR-10 layout', () {
    testWidgets('320x568 dp at 2x text scale renders without overflow', (
      tester,
    ) async {
      await _pumpLibrary(
        tester,
        _apiReturning(_scores),
        physicalSize: const Size(640, 1136),
        devicePixelRatio: 2.0,
        textScale: 2.0,
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);

      // No-results state plus the clear button in the field.
      await tester.enterText(find.byType(TextField), 'zzz');
      await tester.pump();
      // On this screen the message sits below the fold; it must be
      // reachable by scrolling, and nothing may overflow on the way.
      await _scrollListUntilBuilt(
        tester,
        find.text(LibraryMessages.noResultsTitle),
      );
      expect(find.text(LibraryMessages.noResultsTitle), findsOneWidget);
      expect(
        find.byKey(const ValueKey('library-search-clear')),
        findsOneWidget,
      );
      expect(tester.takeException(), isNull);
    });

    testWidgets('320x568 dp with a status bar and untitled scores', (
      tester,
    ) async {
      await _pumpLibrary(
        tester,
        _apiReturning([
          ..._scores,
          const ScoreSummary(scoreId: 7),
          const ScoreSummary(scoreId: 8),
        ]),
        physicalSize: const Size(640, 1136),
        devicePixelRatio: 2.0,
        textScale: 2.0,
        topInset: 24,
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      // At 2x the decorative mark yields its width to the heading.
      expect(find.byKey(const ValueKey('library-header-logo')), findsNothing);
      // Undated untitled scores sort last; scroll to them.
      await _scrollListUntilBuilt(tester, find.text('New Score (1)'));
      expect(find.text('New Score (1)'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('320x568 dp error state renders without overflow', (
      tester,
    ) async {
      await _pumpLibrary(
        tester,
        ScriptedScoreLibraryApi(
          onFetch: () async => throw const ScoreLibraryNetworkException(),
        ),
        physicalSize: const Size(640, 1136),
        devicePixelRatio: 2.0,
        textScale: 2.0,
      );
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });
  });

  group('senior-review round 3', () {
    Future<void> confirmTrashDelete(WidgetTester tester, String title) async {
      await _tapDelete(tester, title);
      await tester.tap(find.text(LibraryMessages.deleteConfirm));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));
    }

    Future<void> confirmSwipeDelete(WidgetTester tester, String title) async {
      await tester.drag(find.text(title), const Offset(-600, 0));
      await tester.pumpAndSettle();
      await tester.tap(find.text(LibraryMessages.deleteConfirm));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));
    }

    Future<void> expectParaisoGoneCleanly(WidgetTester tester) async {
      await tester.enterText(find.byType(TextField), '');
      await tester.pumpAndSettle();
      expect(find.text('Paraiso'), findsNothing);
      // No row is left disabled behind a spinner (_deletingIds is empty).
      expect(find.byType(CircularProgressIndicator), findsNothing);
      expect(find.text('2 Scores • Tap to Listen'), findsOneWidget);
      expect(_visibleTitleOrder(tester), [
        'Bituin Walang Ningning',
        'Bahay Kubo',
      ]);
      expect(tester.takeException(), isNull);
    }

    for (final viaSwipe in [false, true]) {
      final path = viaSwipe ? 'swipe' : 'trash';
      testWidgets('$path delete hidden by a search mid-request still removes '
          'the row', (tester) async {
        final server = Completer<void>();
        final api = _apiReturning(_scores)..onDelete = (_) => server.future;
        await _pumpLibrary(tester, api);
        await tester.pumpAndSettle();

        if (viaSwipe) {
          await confirmSwipeDelete(tester, 'Paraiso');
        } else {
          await confirmTrashDelete(tester, 'Paraiso');
        }
        await tester.enterText(find.byType(TextField), 'zzz');
        await tester.pump();
        expect(find.text('Paraiso'), findsNothing);

        server.complete();
        await tester.pumpAndSettle();
        await expectParaisoGoneCleanly(tester);
      });
    }

    testWidgets('a row hidden during its exit animation is still removed', (
      tester,
    ) async {
      final api = _apiReturning(_scores)..onDelete = (_) async {};
      await _pumpLibrary(tester, api);
      await tester.pumpAndSettle();

      await _tapDelete(tester, 'Paraiso');
      await tester.tap(find.text(LibraryMessages.deleteConfirm));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
      expect(find.text('Paraiso'), findsOneWidget, reason: 'mid-exit');

      await tester.enterText(find.byType(TextField), 'zzz');
      await tester.pump();
      await expectParaisoGoneCleanly(tester);
    });

    testWidgets('a deleting row is disabled and announces "Deleting…"', (
      tester,
    ) async {
      final handle = tester.ensureSemantics();
      final server = Completer<void>();
      final api = _apiReturning(_scores)..onDelete = (_) => server.future;
      await _pumpLibrary(tester, api);
      await tester.pumpAndSettle();

      await confirmTrashDelete(tester, 'Paraiso');
      final deleting = find.bySemanticsLabel(LibraryMessages.deleting);
      expect(deleting, findsWidgets);
      expect(_deleteButtonFor('Paraiso'), findsNothing);
      expect(
        tester.getSemantics(deleting.first),
        isSemantics(hasEnabledState: true, isEnabled: false),
      );
      expect(
        tester.getSemantics(find.text('Paraiso')),
        isSemantics(hasEnabledState: true, isEnabled: false),
      );

      server.complete();
      await tester.pumpAndSettle();
      handle.dispose();
    });

    for (final viaSwipe in [false, true]) {
      final path = viaSwipe ? 'swipe' : 'trash';
      testWidgets('401 on $path delete keeps the row and offers Log In', (
        tester,
      ) async {
        final api = _apiReturning(_scores)
          ..onDelete = (_) async => throw const SessionExpiredException();
        await _pumpLibrary(tester, api);
        await tester.pumpAndSettle();

        if (viaSwipe) {
          await confirmSwipeDelete(tester, 'Paraiso');
        } else {
          await confirmTrashDelete(tester, 'Paraiso');
        }
        await tester.pumpAndSettle();

        expect(find.text('Paraiso'), findsOneWidget);
        expect(find.text(LibraryMessages.sessionExpired), findsOneWidget);
        expect(find.byType(CircularProgressIndicator), findsNothing);
        final action = find.widgetWithText(
          SnackBarAction,
          LibraryMessages.logInAgain,
        );
        expect(action, findsOneWidget);
        await tester.tap(action);
        await tester.pumpAndSettle();
        expect(find.text(_loginMarker), findsOneWidget);
      });
    }

    testWidgets('404 on swipe delete removes the row', (tester) async {
      final api = _apiReturning(_scores)
        ..onDelete = (_) async => throw const ScoreNotFoundException();
      await _pumpLibrary(tester, api);
      await tester.pumpAndSettle();

      await confirmSwipeDelete(tester, 'Paraiso');
      await tester.pumpAndSettle();

      expect(find.text('Paraiso'), findsNothing);
      expect(find.text(LibraryMessages.deleteAlreadyGone), findsOneWidget);
      expect(find.text('2 Scores • Tap to Listen'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('double tap on a card opens Playback once', (tester) async {
      final api = _apiReturning(_scores);
      await _pumpLibrary(tester, api);
      await tester.pumpAndSettle();

      await tester.tap(find.text('Paraiso'));
      await tester.tap(find.text('Paraiso'));
      await tester.pumpAndSettle();
      expect(find.text(_playbackMarker), findsOneWidget);
      expect(api.openedIds, [102]);

      Navigator.of(tester.element(find.text(_playbackMarker))).pop();
      await tester.pumpAndSettle();
      expect(find.text(_playbackMarker), findsNothing);
      expect(find.text(LibraryMessages.title), findsOneWidget);

      // The guard resets once Playback is closed.
      await tester.tap(find.text('Paraiso'));
      await tester.pumpAndSettle();
      expect(find.text(_playbackMarker), findsOneWidget);
    });

    testWidgets('double tap on the trash opens one dialog', (tester) async {
      final api = _apiReturning(_scores)..onDelete = (_) async {};
      await _pumpLibrary(tester, api);
      await tester.pumpAndSettle();

      final trash = find.descendant(
        of: find
            .ancestor(of: find.text('Paraiso'), matching: find.byType(Material))
            .first,
        matching: find.byIcon(Icons.delete_rounded),
      );
      await tester.tap(trash);
      await tester.tap(trash);
      await tester.pumpAndSettle();
      expect(find.text(LibraryMessages.deleteDialogTitle), findsOneWidget);

      await tester.tap(find.text(LibraryMessages.deleteCancel));
      await tester.pumpAndSettle();
      expect(find.text(LibraryMessages.deleteDialogTitle), findsNothing);
    });

    testWidgets('concurrent reloads share one fetch', (tester) async {
      var first = true;
      final pending = Completer<List<ScoreSummary>>();
      final api = ScriptedScoreLibraryApi(
        onFetch: () {
          if (first) {
            first = false;
            return Future.value(_scores);
          }
          return pending.future;
        },
      );
      await _pumpLibrary(tester, api);
      await tester.pumpAndSettle();
      expect(api.fetchCalls, 1);

      final container = ProviderScope.containerOf(
        tester.element(find.byType(ScoreLibraryScreen)),
      );
      final notifier = container.read(scoreLibraryProvider.notifier);
      final a = notifier.reload();
      final b = notifier.reload();
      expect(api.fetchCalls, 2);
      pending.complete(_scores);
      await Future.wait([a, b]);
      await tester.pumpAndSettle();

      // A later reload fetches again.
      unawaited(notifier.reload());
      expect(api.fetchCalls, 3);
      await tester.pumpAndSettle();
    });

    testWidgets('opening a score records it through the API', (tester) async {
      final api = _apiReturning(_scores);
      await _pumpLibrary(tester, api);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Bahay Kubo'));
      await tester.pumpAndSettle();
      expect(api.openedIds, [103]);
    });

    testWidgets('a failed open record still opens the score', (tester) async {
      final api = _apiReturning(_scores)
        ..onRecordOpened = (_) async =>
            throw const ScoreLibraryNetworkException();
      await _pumpLibrary(tester, api);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Bahay Kubo'));
      await tester.pumpAndSettle();
      expect(find.text(_playbackMarker), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('Add Score card is hidden while searching', (tester) async {
      await _pumpLibrary(tester, _apiReturning(_scores));
      await tester.pumpAndSettle();
      expect(find.text(LibraryMessages.addScoreTitle), findsOneWidget);

      await tester.enterText(find.byType(TextField), 'para');
      await tester.pump();
      expect(find.text(LibraryMessages.addScoreTitle), findsNothing);
      // AC8 stays reachable from the nav bar.
      expect(find.bySemanticsLabel('Capture'), findsOneWidget);

      await tester.enterText(find.byType(TextField), '');
      await tester.pump();
      expect(find.text(LibraryMessages.addScoreTitle), findsOneWidget);
    });

    testWidgets('320x568 at 2x: the first result is visible while typing', (
      tester,
    ) async {
      await _pumpLibrary(
        tester,
        _apiReturning(_scores),
        physicalSize: const Size(640, 1136),
        devicePixelRatio: 2.0,
        textScale: 2.0,
        topInset: 24,
      );
      await tester.pumpAndSettle();

      await tester.enterText(find.byType(TextField), 'kubo');
      await tester.pump();

      final card = tester.getRect(
        find.ancestor(
          of: find.text('Bahay Kubo'),
          matching: find.byType(ScoreCard),
        ),
      );
      final visibleTop = tester.getRect(find.byType(LibraryHeader)).bottom;
      final visibleBottom = tester.getRect(find.byType(LibraryBottomNav)).top;
      expect(visibleBottom, greaterThan(visibleTop));
      expect(card.top, lessThan(visibleBottom));
      expect(card.bottom, greaterThan(visibleTop));
      expect(tester.takeException(), isNull);
    });

    testWidgets('320 dp at 2x: "Settings" is shown whole, not ellipsized', (
      tester,
    ) async {
      await _pumpLibrary(
        tester,
        _apiReturning(_scores),
        physicalSize: const Size(640, 1136),
        devicePixelRatio: 2.0,
        textScale: 2.0,
      );
      await tester.pumpAndSettle();

      for (final label in ['Library', 'Capture', 'Settings']) {
        final paragraph = tester.renderObject<RenderParagraph>(
          find.text(label),
        );
        expect(paragraph.didExceedMaxLines, isFalse, reason: label);
        expect(paragraph.text.toPlainText(), label);
        final rect = tester.getRect(find.text(label));
        expect(rect.left, greaterThanOrEqualTo(0), reason: label);
        expect(rect.right, lessThanOrEqualTo(320), reason: label);
      }
      // Settings fits inside its own slot (27% of the width), so it can't
      // run under the Capture label.
      final settings = tester.getRect(find.text('Settings'));
      expect(settings.width, lessThanOrEqualTo(320 * 0.27 + 0.5));
      expect(
        settings.left,
        greaterThanOrEqualTo(tester.getRect(find.text('Capture')).right),
      );
    });
  });

  group('accessibility guidelines', () {
    Future<void> expectGuidelines(WidgetTester tester) async {
      await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
      await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
      await expectLater(tester, meetsGuideline(textContrastGuideline));
    }

    testWidgets('list state', (tester) async {
      final handle = tester.ensureSemantics();
      await _pumpLibrary(tester, _apiReturning(_scores));
      await tester.pumpAndSettle();
      await expectGuidelines(tester);
      handle.dispose();
    });

    testWidgets('error state', (tester) async {
      final handle = tester.ensureSemantics();
      await _pumpLibrary(
        tester,
        ScriptedScoreLibraryApi(
          onFetch: () async => throw const ScoreLibraryServerException(),
        ),
      );
      await tester.pumpAndSettle();
      await expectGuidelines(tester);
      handle.dispose();
    });

    testWidgets('no-results state', (tester) async {
      final handle = tester.ensureSemantics();
      await _pumpLibrary(tester, _apiReturning(_scores));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), 'zzz');
      await tester.pump();
      // Dismiss the keyboard focus so the caret isn't mid-blink.
      FocusManager.instance.primaryFocus?.unfocus();
      await tester.pumpAndSettle();
      await expectGuidelines(tester);
      handle.dispose();
    });
  });
}
