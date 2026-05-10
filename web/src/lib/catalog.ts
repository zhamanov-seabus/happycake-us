import yaml from 'js-yaml';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const CATALOG_PATH = resolve(here, '../../../data/catalog.yml');

export interface Allergens {
  contains: string[];
  traces: string[];
  note?: string;
}

export interface Product {
  id: string;
  variation_id: string;
  kitchen_product_id: string;
  name: string;
  display_name: string;
  slug: string;
  category: string;
  price_usd: number;
  weight: string;
  description: string;
  photo: string;
  tags: string[];
  lead_time_minutes?: number;
  requires_owner_approval?: boolean;
  allergens?: Allergens;
  dietary?: string[];
  pairs_with?: string[];
}

export interface Category {
  id: string;
  name: string;
  blurb: string;
}

export interface Business {
  name: string;
  legal_name: string;
  tagline: string;
  slogan: string;
  location: { city: string; state: string; region: string };
  hours: Record<string, string>;
  channels: { website: string; whatsapp: string };
  closing_pattern: string;
}

export interface Catalog {
  products: Product[];
  categories: Category[];
  business: Business;
}

let cached: Catalog | null = null;

export function getCatalog(): Catalog {
  if (!cached) {
    cached = yaml.load(readFileSync(CATALOG_PATH, 'utf-8')) as Catalog;
  }
  return cached;
}

export function priceLabel(p: Product): string {
  return `$${p.price_usd.toFixed(2)}`;
}
