import { useQuery } from "@tanstack/react-query";

import { api, Branding, Comparable, Contact, ContactKind, Contract, Digest, LineItem, MediaItem, Milestone, Project, QuoteRequest, Receipt, Referrals, ShoppingItem, Snag, SpendTrend } from "@/src/api";
import { queryClient } from "@/src/query-client";

export const useProject = () => useQuery({ queryKey: ["project"], queryFn: () => api<Project>("/project") });
export const useLineItems = () => useQuery({ queryKey: ["line-items"], queryFn: () => api<LineItem[]>("/line-items") });
export const useSpendTrend = () => useQuery({ queryKey: ["line-items", "trend"], queryFn: () => api<SpendTrend>("/line-items/trend") });
export const useReceipts = () => useQuery({ queryKey: ["receipts"], queryFn: () => api<Receipt[]>("/receipts") });
export const useMedia = () => useQuery({ queryKey: ["media"], queryFn: () => api<MediaItem[]>("/media") });
export const useContacts = (kind: ContactKind, enabled = true) =>
  useQuery({ queryKey: ["contacts", kind], queryFn: () => api<Contact[]>(`/contacts?kind=${kind}`), enabled });
export const useComparables = (enabled: boolean) =>
  useQuery({ queryKey: ["comparables"], queryFn: () => api<Comparable[]>("/project/comparables"), enabled });
export const useMilestones = () => useQuery({ queryKey: ["milestones"], queryFn: () => api<Milestone[]>("/milestones") });
export const useBranding = () => useQuery({ queryKey: ["branding"], queryFn: () => api<Branding>("/branding") });
export const useContracts = () => useQuery({ queryKey: ["contracts"], queryFn: () => api<Contract[]>("/stage-payments") });
export const useSnags = () => useQuery({ queryKey: ["snags"], queryFn: () => api<Snag[]>("/snags") });
export const useReferrals = () => useQuery({ queryKey: ["referrals"], queryFn: () => api<Referrals>("/referrals") });
export const useQuotes = () => useQuery({ queryKey: ["quotes"], queryFn: () => api<QuoteRequest[]>("/quotes") });
export const useQuote = (id: string) =>
  useQuery({ queryKey: ["quotes", id], queryFn: () => api<QuoteRequest>(`/quotes/${id}`), refetchInterval: 10000 });

export type ProjectRow = Project & { active: boolean };
export const projectsQuery = { queryKey: ["projects"], queryFn: () => api<ProjectRow[]>("/projects"), staleTime: 30000 };
export const useProjects = () => useQuery(projectsQuery);
export const prefetchProjects = () => queryClient.prefetchQuery(projectsQuery);
export const useShopping = () => useQuery({ queryKey: ["shopping"], queryFn: () => api<ShoppingItem[]>("/shopping") });
export const useDigest = (week: number) => useQuery({ queryKey: ["digest", week], queryFn: () => api<Digest>(`/digest?week=${week}`) });

export const invalidate = (...keys: string[]) => Promise.all(keys.map((k) => queryClient.invalidateQueries({ queryKey: [k] })));
