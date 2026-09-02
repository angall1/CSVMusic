#include <glib.h>
#include <glib/gstdio.h>
#include <gpod/itdb.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static void print_error(const char *context, GError *error)
{
	fprintf(stderr, "%s: %s\n", context, error && error->message ? error->message : "unknown error");
	if (error) {
		g_error_free(error);
	}
}

static gint compare_playlist_names(gconstpointer left, gconstpointer right)
{
	const Itdb_Playlist *a = left;
	const Itdb_Playlist *b = right;
	return g_utf8_collate(a && a->name ? a->name : "", b && b->name ? b->name : "");
}

static void sort_playlists_alphabetically(Itdb_iTunesDB *db)
{
	Itdb_Playlist *master = itdb_playlist_mpl(db);
	if (master) {
		db->playlists = g_list_remove(db->playlists, master);
	}
	db->playlists = g_list_sort(db->playlists, compare_playlist_names);
	if (master) {
		db->playlists = g_list_prepend(db->playlists, master);
	}
}

static Itdb_Track *find_track(Itdb_iTunesDB *db, const char *title, const char *artist)
{
	for (GList *node = db->tracks; node; node = node->next) {
		Itdb_Track *track = node->data;
		if (g_ascii_strcasecmp(track->title ? track->title : "", title) == 0 &&
			g_ascii_strcasecmp(track->artist ? track->artist : "", artist) == 0) {
			return track;
		}
	}
	return NULL;
}

static void remove_duplicate_tracks(Itdb_iTunesDB *db, Itdb_Track *keep)
{
	GList *node = db->tracks;
	while (node) {
		GList *next = node->next;
		Itdb_Track *candidate = node->data;
		if (candidate != keep &&
			g_ascii_strcasecmp(candidate->title ? candidate->title : "", keep->title ? keep->title : "") == 0 &&
			g_ascii_strcasecmp(candidate->artist ? candidate->artist : "", keep->artist ? keep->artist : "") == 0) {
			for (GList *playlist_node = db->playlists; playlist_node; playlist_node = playlist_node->next) {
				Itdb_Playlist *playlist = playlist_node->data;
				GList *member = g_list_find(playlist->members, candidate);
				if (!member) {
					continue;
				}
				if (g_list_find(playlist->members, keep)) {
					itdb_playlist_remove_track(playlist, candidate);
				} else {
					member->data = keep;
				}
			}
			gchar *filename = itdb_filename_on_ipod(candidate);
			if (filename) {
				g_remove(filename);
				printf("REMOVED_DUPLICATE\t%s\n", candidate->ipod_path ? candidate->ipod_path : "");
				g_free(filename);
			}
			itdb_track_remove(candidate);
		}
		node = next;
	}
}

static int inspect_ipod(const char *mountpoint)
{
	GError *error = NULL;
	Itdb_iTunesDB *db = itdb_parse(mountpoint, &error);
	if (!db) {
		print_error("Could not read the iPod database", error);
		return 2;
	}
	printf("TRACKS\t%u\n", g_list_length(db->tracks));
	for (GList *node = db->playlists; node; node = node->next) {
		Itdb_Playlist *playlist = node->data;
		printf("PLAYLIST\t%s\t%u\n", playlist->name ? playlist->name : "", g_list_length(playlist->members));
	}
	itdb_free(db);
	return 0;
}

static int find_tracks(const char *mountpoint, const char *query)
{
	GError *error = NULL;
	Itdb_iTunesDB *db = itdb_parse(mountpoint, &error);
	if (!db) {
		print_error("Could not read the iPod database", error);
		return 2;
	}
	gchar *needle = g_utf8_strdown(query, -1);
	for (GList *node = db->tracks; node; node = node->next) {
		Itdb_Track *track = node->data;
		gchar *title = g_utf8_strdown(track->title ? track->title : "", -1);
		if (strstr(title, needle)) {
			printf("TRACK_DETAIL\t%s\t%s\t%u\t%d\t%s\t%s\n",
				track->title ? track->title : "", track->artist ? track->artist : "", track->size,
				track->tracklen, track->comment ? track->comment : "", track->ipod_path ? track->ipod_path : "");
			for (GList *playlist_node = db->playlists; playlist_node; playlist_node = playlist_node->next) {
				Itdb_Playlist *playlist = playlist_node->data;
				if (g_list_find(playlist->members, track)) {
					printf("MEMBER_OF\t%s\n", playlist->name ? playlist->name : "");
				}
			}
		}
		g_free(title);
	}
	g_free(needle);
	itdb_free(db);
	return 0;
}

static int delete_playlist(const char *mountpoint, const char *playlist_name)
{
	GError *error = NULL;
	Itdb_iTunesDB *db = itdb_parse(mountpoint, &error);
	if (!db) {
		print_error("Could not read the iPod database", error);
		return 2;
	}
	Itdb_Playlist *playlist = itdb_playlist_by_name(db, (gchar *)playlist_name);
	if (!playlist || playlist == itdb_playlist_mpl(db)) {
		fprintf(stderr, "Playlist not found or cannot be deleted: %s\n", playlist_name);
		itdb_free(db);
		return 3;
	}
	itdb_playlist_remove(playlist);
	if (!itdb_write(db, &error)) {
		print_error("Could not write the iPod database", error);
		itdb_free(db);
		return 4;
	}
	printf("DELETED\t%s\n", playlist_name);
	itdb_free(db);
	return 0;
}

static int sync_playlist(const char *mountpoint, const char *playlist_name)
{
	GError *error = NULL;
	Itdb_iTunesDB *db = itdb_parse(mountpoint, &error);
	if (!db) {
		print_error("Could not read the iPod database", error);
		return 2;
	}
	Itdb_Playlist *playlist = NULL;
	while ((playlist = itdb_playlist_by_name(db, (gchar *)playlist_name)) != NULL && playlist != itdb_playlist_mpl(db)) {
		itdb_playlist_remove(playlist);
	}
	playlist = itdb_playlist_new(playlist_name, FALSE);
	itdb_playlist_add(db, playlist, -1);

	char *line = NULL;
	size_t capacity = 0;
	unsigned int added = 0;
	unsigned int reused = 0;
	unsigned int failed = 0;
	while (getline(&line, &capacity, stdin) != -1) {
		g_strchomp(line);
		if (!line[0]) {
			continue;
		}
		gchar **field = g_strsplit(line, "\t", 10);
		if (g_strv_length(field) < 10) {
			fprintf(stderr, "Invalid manifest row\n");
			failed++;
			g_strfreev(field);
			continue;
		}
		Itdb_Track *track = find_track(db, field[1], field[2]);
		gboolean selected_alternative = g_str_has_prefix(field[9], "selected:");
		if (track) {
			guint32 source_size = (guint32)g_ascii_strtoull(field[6], NULL, 10);
			gchar *identity = g_strdup_printf("CSVMusic:%s", field[9]);
			gboolean known_different = track->comment && g_str_has_prefix(track->comment, "CSVMusic:") && strcmp(track->comment, identity) != 0;
			if (selected_alternative && (track->size != source_size || known_different)) {
				gchar *destination = itdb_filename_on_ipod(track);
				if (!destination || !itdb_cp(field[0], destination, &error)) {
					print_error(field[0], error);
					error = NULL;
					g_free(destination);
					g_free(identity);
					failed++;
					g_strfreev(field);
					continue;
				}
				g_free(destination);
				g_free(track->title);
				g_free(track->artist);
				g_free(track->album);
				g_free(track->comment);
				track->title = g_strdup(field[1]);
				track->artist = g_strdup(field[2]);
				track->album = g_strdup(field[3]);
				track->comment = identity;
				track->track_nr = atoi(field[4]);
				track->tracklen = atoi(field[5]);
				track->size = source_size;
				track->bitrate = atoi(field[7]);
				track->samplerate = (guint16)atoi(field[8]);
				track->time_modified = time(NULL);
				added++;
				printf("REPLACED\t%s\t%s\n", track->artist, track->title);
			} else {
				g_free(identity);
				reused++;
			}
		} else {
			track = itdb_track_new();
			track->title = g_strdup(field[1]);
			track->artist = g_strdup(field[2]);
			track->album = g_strdup(field[3]);
			track->comment = g_strdup_printf("CSVMusic:%s", field[9]);
			track->filetype = g_strdup("MP3 audio file");
			track->track_nr = atoi(field[4]);
			track->tracklen = atoi(field[5]);
			track->size = (guint32)g_ascii_strtoull(field[6], NULL, 10);
			track->bitrate = atoi(field[7]);
			track->samplerate = (guint16)atoi(field[8]);
			track->mediatype = ITDB_MEDIATYPE_AUDIO;
			track->time_added = time(NULL);
			track->time_modified = time(NULL);
			itdb_track_add(db, track, -1);
			itdb_playlist_add_track(itdb_playlist_mpl(db), track, -1);
			if (!itdb_cp_track_to_ipod(track, field[0], &error)) {
				print_error(field[0], error);
				error = NULL;
				itdb_track_remove(track);
				failed++;
				g_strfreev(field);
				continue;
			}
			added++;
		}
		if (selected_alternative) {
			remove_duplicate_tracks(db, track);
		}
		itdb_playlist_add_track(playlist, track, -1);
		printf("TRACK\t%s\t%s\n", track->artist ? track->artist : "", track->title ? track->title : "");
		g_strfreev(field);
	}
	free(line);

	if (failed) {
		fprintf(stderr, "Aborting database write because %u track(s) failed\n", failed);
		itdb_free(db);
		return 3;
	}
	sort_playlists_alphabetically(db);
	if (!itdb_write(db, &error)) {
		print_error("Could not write the iPod database", error);
		itdb_free(db);
		return 4;
	}
	printf("COMPLETE\t%s\t%u\t%u\t%u\n", playlist_name, added, reused, g_list_length(playlist->members));
	itdb_free(db);
	return 0;
}

int main(int argc, char **argv)
{
	if (argc == 3 && strcmp(argv[1], "inspect") == 0) {
		return inspect_ipod(argv[2]);
	}
	if (argc == 4 && strcmp(argv[1], "sync") == 0) {
		return sync_playlist(argv[2], argv[3]);
	}
	if (argc == 4 && strcmp(argv[1], "delete") == 0) {
		return delete_playlist(argv[2], argv[3]);
	}
	if (argc == 4 && strcmp(argv[1], "find") == 0) {
		return find_tracks(argv[2], argv[3]);
	}
	fprintf(stderr, "Usage: %s inspect MOUNTPOINT | sync MOUNTPOINT PLAYLIST < manifest.tsv | delete MOUNTPOINT PLAYLIST\n", argv[0]);
	return 1;
}
