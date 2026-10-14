import { useQuery } from "@tanstack/react-query";

import { api, Comparable, Contact, ContactKind, LineItem, MediaItem, Project, Receipt } from "@/src/api";
import { queryClient } from "@/src/query-client";

export const useProject = () => useQuery({ queryKey: ["project"], queryFn: () => api<Project>("/project") });
export const useLineItems = () => useQuery({ queryKey: ["line-items"], queryFn: () => api<LineItem[]>("/line-items") });
export const useReceipts = () => useQuery({ queryKey: ["receipts"], queryFn: () => api<Receipt[]>("/receipts") });
export const useMedia = () => useQuery({ queryKey: ["media"], queryFn: () => api<MediaItem[]>("/media") });
export const useContacts = (kind: ContactKind, enabled = true) =>
  useQuery({ queryKey: ["contacts", kind], queryFn: () => api<Contact[]>(`/contacts?kind=${kind}`), enabled });
export const useComparables = (enabled: boolean) =>
  useQuery({ queryKey: ["comparables"], queryFn: () => api<Comparable[]>("/project/comparables"), enabled });

export const invalidate = (...keys: string[]) => Promise.all(keys.map((k) => queryClient.invalidateQueries({ queryKey: [k] })));
