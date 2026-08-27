import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download as DownloadIcon, Search } from "lucide-react";
import { useState, type FormEvent } from "react";
import { downloadUrl, post } from "../api";
import { EmptyState, ErrorState, PageHeader, StatusPill, Time } from "../components/ui";
import { usePollingQuery } from "../hooks";
import { formatBytes, shortHash } from "../lib/format";
import type { Book, Download } from "../types";

export function BooksPage() {
  const [draft, setDraft] = useState("");
  const [query, setQuery] = useState("");
  const queryClient = useQueryClient();
  const books = usePollingQuery<{ items: Book[]; next_cursor?: string | null }>(
    ["books", query],
    `/api/books?limit=100${query ? `&q=${encodeURIComponent(query)}` : ""}`,
  );
  const downloads = usePollingQuery<{ downloads: Download[] }>(["downloads"], "/api/downloads?limit=100");
  const mutation = useMutation({
    mutationFn: (bookId: string) => post(`/api/books/${encodeURIComponent(bookId)}/download`, {
      skip_existing: true,
      include_book_id: true,
    }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["books"] }),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    setQuery(draft.trim());
  }

  return (
    <>
      <PageHeader
        eyebrow="Library"
        title="书籍与 TXT 下载"
        description="这里只交付免费章节 TXT，不提供在线阅读，也不会请求付费正文。"
        actions={
          <form className="search-form" onSubmit={submit}>
            <Search size={15} aria-hidden="true" />
            <input
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="书名或作者"
              aria-label="筛选书籍"
            />
            <button className="button secondary" type="submit">筛选</button>
          </form>
        }
      />
      {books.error ? <ErrorState error={books.error} /> : null}
      {mutation.error ? <ErrorState error={mutation.error} /> : null}
      <section className="panel">
        <div className="panel-heading">
          <div><p className="eyebrow">Indexed</p><h2>已索引书籍</h2></div>
          <span className="count-label">{books.data?.items.length ?? 0} 本</span>
        </div>
        {(books.data?.items.length ?? 0) === 0 ? (
          <EmptyState>暂无索引结果。先执行一次榜单 / 新书同步。</EmptyState>
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>书名</th><th>作者</th><th>字数</th><th>付费标记</th><th>下载</th><th /></tr></thead>
              <tbody>
                {books.data?.items.map((book) => (
                  <tr key={book.book_id}>
                    <td><strong>{book.book_name || `#${book.book_id}`}</strong><small className="cell-sub">{book.book_id}</small></td>
                    <td>{book.author_name || "—"}</td>
                    <td>{Number(book.total_word_count ?? 0).toLocaleString("zh-CN")}</td>
                    <td><StatusPill value={book.is_paid ? "paid-index" : "free-index"} /></td>
                    <td><StatusPill value={book.downloaded ? "downloaded" : "not_downloaded"} /></td>
                    <td className="align-right">
                      <button
                        className="icon-button"
                        type="button"
                        aria-label={`下载 ${book.book_name}`}
                        onClick={() => mutation.mutate(book.book_id)}
                        disabled={mutation.isPending}
                      ><DownloadIcon size={16} /></button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div><p className="eyebrow">Artifacts</p><h2>可下载文件</h2></div>
          <span className="count-label">{downloads.data?.downloads.length ?? 0} 个</span>
        </div>
        {(downloads.data?.downloads.length ?? 0) === 0 ? (
          <EmptyState>暂无 TXT 文件。</EmptyState>
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>书名</th><th>生成时间</th><th>大小</th><th>SHA-256</th><th /></tr></thead>
              <tbody>
                {downloads.data?.downloads.map((item) => (
                  <tr key={item.id}>
                    <td>{item.book_name}</td>
                    <td><Time value={item.created_at} /></td>
                    <td>{formatBytes(item.file_size)}</td>
                    <td><code>{shortHash(item.sha256)}</code></td>
                    <td className="align-right">
                      <a className="button small secondary" href={downloadUrl(item.id)} download>
                        <DownloadIcon size={14} />TXT
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
