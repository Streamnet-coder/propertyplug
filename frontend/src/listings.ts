/** Deep links to live listings on the big UK portals (they have no public listings API), pre-searched on a postcode and radius. */
const slug = (pc: string) => pc.trim().toLowerCase().replace(/\s+/g, "-");
const RM_RADII = [0.25, 0.5, 1, 3, 5, 10];
const rmRadius = (m: number) => RM_RADII.find((r) => r >= m) ?? 10;

export type Listing = { id: string; label: string; url: string };

export function listingLinks(postcode: string, miles: number, kind: "sale" | "rent"): Listing[] {
  const q = encodeURIComponent(postcode.trim().toUpperCase());
  const s = slug(postcode);
  return kind === "sale"
    ? [
        { id: "rightmove", label: "Rightmove", url: `https://www.rightmove.co.uk/property-for-sale/search.html?searchLocation=${q}&radius=${rmRadius(miles)}` },
        { id: "zoopla", label: "Zoopla", url: `https://www.zoopla.co.uk/for-sale/property/${s}/?q=${q}&radius=${miles}&search_source=for-sale` },
        { id: "onthemarket", label: "OnTheMarket", url: `https://www.onthemarket.com/for-sale/property/${s}/?radius=${miles}` },
      ]
    : [
        { id: "rightmove", label: "Rightmove", url: `https://www.rightmove.co.uk/property-to-rent/search.html?searchLocation=${q}&radius=${rmRadius(miles)}` },
        { id: "zoopla", label: "Zoopla", url: `https://www.zoopla.co.uk/to-rent/property/${s}/?q=${q}&radius=${miles}&search_source=to-rent` },
        { id: "onthemarket", label: "OnTheMarket", url: `https://www.onthemarket.com/to-rent/property/${s}/?radius=${miles}` },
      ];
}

/** Rightmove's sold-price history page for a single postcode. */
export const rightmoveSoldUrl = (postcode: string) => `https://www.rightmove.co.uk/house-prices/${slug(postcode)}.html`;
