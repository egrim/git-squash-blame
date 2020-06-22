from collections import defaultdict
import io

from git import Repo, IndexFile, Blob
from gitdb import IStream

import click


def make_blob(repo, blob_bytes, mode, path):
    stream = io.BytesIO(blob_bytes)
    istream = repo.odb.store(IStream(Blob.type, len(blob_bytes), stream))
    return Blob(repo, istream.binsha, mode, path)


@click.command()
@click.option("--preserve-committers", is_flag=True, default=False)
@click.version_option()
def squash_blame(preserve_committers):
    """Squash history while preserving blame"""
    repo = Repo()
    head_commit = repo.head.commit
    mutated_blobs = []
    author_blob_lists = defaultdict(list)

    with click.progressbar(head_commit.tree.traverse()) as git_objects:
        for blob in git_objects:
            if isinstance(blob, Blob):
                blob_bytes = blob.data_stream.read()
                mutated_blob_bytes = blob_bytes.replace(b"\n", b"\r\n")
                mutated_blob = make_blob(repo, mutated_blob_bytes, blob.mode, blob.path)
                mutated_blobs.append(mutated_blob)

                author_lines = defaultdict(set)
                for blame in repo.blame_incremental(head_commit, blob.path):
                    author_lines[blame.commit.author].update(blame.linenos)

                for author, authors_line_numbers in author_lines.items():
                    authors_fixed_blob_bytes_lines = []
                    for line_number, line in enumerate(
                        mutated_blob_bytes.splitlines(keepends=True), start=1
                    ):
                        if line_number in authors_line_numbers:
                            line = line.replace(b"\r\n", b"\n")
                        authors_fixed_blob_bytes_lines.append(line)

                    authors_fixed_blob_bytes = b"".join(authors_fixed_blob_bytes_lines)
                    authors_fixed_blob = make_blob(
                        repo, authors_fixed_blob_bytes, blob.mode, blob.path
                    )
                    author_blob_lists[author].append(authors_fixed_blob)

    base_index = IndexFile.from_tree(repo, head_commit)
    base_index.add(mutated_blobs, write=False)
    new_root = base_index.commit(
        message="Initial commit", parent_commits=[], head=False
    )

    author_commits = []
    for author, author_blobs in author_blob_lists.items():
        index = IndexFile.from_tree(repo, new_root)
        index.add(author_blobs, write=False)
        author_commits.append(
            index.commit(
                message=f"Squash while preserving git-blame for {author.name}",
                parent_commits=[new_root],
                head=False,
                author=author,
                committer=author if preserve_committers else None,
            )
        )

    final_index = IndexFile.from_tree(repo, head_commit)
    final_commit = final_index.commit(
        message="Merge commits that preserve git-blame",
        parent_commits=author_commits,
        head=False,
    )

    print(final_commit.hexsha)


if __name__ == "__main__":
    squash_blame()
