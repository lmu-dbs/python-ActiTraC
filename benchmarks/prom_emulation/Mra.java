import java.util.*;

/**
 * ProM's MRA features, reimplemented from reading MaxRepeatAlphabetDistanceXLog,
 * FeatureExtraction, FeatureSelection, EquivalenceClass and EncodeActivitySet.
 * It uses the same Java collections with the same insertion order, so HashSet
 * iteration is the real one. The suffix tree inserts suffixes in order with the
 * same child ordering as UkkonenSuffixTree.
 */
class Mra {
    static boolean SORTED = false;     // TreeSet instead of HashSet for String sets
    static boolean ALLSTREAMS = false; // getRepeats keeps all streams
    static boolean TRUELEN = false;    // FeatureSelection uses the true encoding length
    static boolean NOFILTER = false;

    static int SEED = 0;               // seeded pseudo-random iteration order for String sets
    static int mix(String x) { int h = x.hashCode() ^ SEED * 0x9E3779B9; h ^= h >>> 16; h *= 0x85EBCA6B; h ^= h >>> 13; h *= 0xC2B2AE35; return h ^ (h >>> 16); }
    static Set<String> set() {
        if (SEED != 0) return new TreeSet<String>(Comparator.comparingInt(Mra::mix).thenComparing(Comparator.<String>naturalOrder()));
        return SORTED ? new TreeSet<String>() : new HashSet<String>();
    }

    static final String[] LOW = "abcdefghijklmnopqrstuvwxyz".split(""), UP = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split(""),
        ALPHA = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ".split(""),
        LOWINT = "abcdefghijklmnopqrstuvwxyz0123456789".split(""), INT = "0123456789".split(""),
        ALL = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789".split("");

    static final class Enc {
        Map<String, String> a2c = new HashMap<>(), c2a = new HashMap<>(); int len = 2;
        Enc(Set<String> s) {
            int n = s.size();
            if (n <= ALL.length) { len = 1; one(s, ALL); }
            else if (n <= LOW.length * INT.length) two(s, LOW, INT);
            else if (n <= ALPHA.length * INT.length) two(s, ALPHA, INT);
            else if (n <= LOWINT.length * UP.length) two(s, LOWINT, UP);
            else if (n <= ALL.length * ALL.length) two(s, ALL, ALL);
            else if (n <= LOW.length * UP.length * INT.length) { len = 3; three(s, LOW, UP, INT); }
            else if (n <= ALL.length * ALL.length * ALL.length) { len = 3; three(s, ALL, ALL, ALL); }
            else throw new RuntimeException("overflow");
        }
        void put(String a, String c) { a2c.put(a, c); c2a.put(c, a); }
        void one(Set<String> s, String[] x) { int i = 0; for (String a : s) put(a, x[i++]); }
        void two(Set<String> s, String[] x, String[] y) { int i = 0; for (String a : s) { put(a, x[i / y.length] + y[i % y.length]); i++; } }
        void three(Set<String> s, String[] x, String[] y, String[] z) {
            int i = 0;
            for (String a : s) { put(a, x[i / (z.length * y.length)] + y[(i / z.length) % y.length] + z[i % z.length]); i++; }
        }
    }

    // ---- suffix tree
    static final class Node {
        Node parent; ArrayList<Node> kids = new ArrayList<>(2); int start, end, path; boolean leaf = true, diverse; int left;
        Node(Node p, int s, int e, int pp) { parent = p; start = s; end = e; path = pp; }
    }

    static final class Tree {
        final String seq; final int enc; final int[] sym; final int m; final Node root = new Node(null, 0, 0, 0);
        Tree(int enc, String stream) {
            this.enc = enc;
            StringBuilder pre = new StringBuilder(), eos = new StringBuilder();
            for (int i = 0; i < enc; i++) { pre.append('.'); eos.append('.'); }
            seq = pre + stream + eos;
            m = stream.length() / enc + 1;
            sym = new int[m + 1];
            HashMap<String, Integer> id = new HashMap<>();
            for (int i = 0; i <= m; i++) {
                String t = seq.substring(i * enc, (i + 1) * enc);
                Integer v = id.get(t);
                if (v == null) { v = id.size(); id.put(t, v); }
                sym[i] = v;
            }
            root.leaf = false;
            // Ukkonen creates leaves in suffix order. The last symbol terminates each.
            for (int j = 1; j <= m; j++) insert(j);
            mark(root);
        }
        void insert(int j) {
            Node cur = root; int i = j;
            while (true) {
                Node child = null;
                for (Node c : cur.kids) if (sym[c.start] == sym[i]) { child = c; break; }
                if (child == null) {
                    Node l = new Node(cur, i, m, j); l.left = sym[j - 1];
                    cur.kids.add(l);
                    return;
                }
                int e = child.leaf ? m : child.end, k = child.start;
                while (k <= e && sym[k] == sym[i]) { k++; i++; }
                if (k > e) { cur = child; continue; }
                Node in = new Node(cur, child.start, k - 1, child.path); in.leaf = false;
                child.start = k;
                cur.kids.remove(child); cur.kids.add(in);
                in.kids.add(child); child.parent = in;
                Node l = new Node(in, i, m, j); l.left = sym[j - 1];
                in.kids.add(l);
                return;
            }
        }
        // returns the single left symbol of the subtree, or -1 when diverse
        int mark(Node n) {
            if (n.leaf) return n.left;
            int one = -2;
            for (Node c : n.kids) {
                int v = mark(c);
                if (v == -1) one = -1;
                else if (one == -2) one = v;
                else if (one != v) one = -1;
            }
            n.diverse = one == -1;
            return one;
        }
        void diverse(Node n, List<Node> out) {
            if (n.diverse) out.add(n);
            for (Node c : n.kids) diverse(c, out);
        }
        String label(Node n) { return seq.substring(n.path * enc, (n.end + 1) * enc); }
        Set<String> maximal() {
            List<Node> ns = new ArrayList<>(); diverse(root, ns);
            String term = seq.substring(0, enc);
            Set<String> out = set();
            for (Node n : ns) { String r = label(n); if (!r.equals(term)) out.add(r); }
            return out;
        }
        Set<String> superMaximal() {
            List<Node> ns = new ArrayList<>(); diverse(root, ns);
            Set<String> out = set();
            for (Node n : ns) {
                boolean all = true; HashSet<Integer> lefts = new HashSet<>();
                for (Node c : n.kids) { if (!c.leaf) { all = false; break; } lefts.add(c.left); }
                if (all && lefts.size() == n.kids.size()) out.add(label(n));
            }
            return out;
        }
    }

    // ---- EquivalenceClass
    static final Comparator<String> DESC = (a, b) -> a.length() < b.length() ? 1 : -1;

    static Map<Set<String>, Set<String>> classes(int enc, Set<String> features) {
        Map<Set<String>, Set<String>> map = new HashMap<>();
        for (String f : features) {
            int n = f.length() / enc;
            Set<String> alpha = new TreeSet<>();
            for (int i = 0; i < n; i++) alpha.add(f.substring(i * enc, (i + 1) * enc));
            Set<String> eq = map.get(alpha);
            if (eq == null) eq = new TreeSet<>(DESC);
            eq.add(f);
            map.put(alpha, eq);
        }
        return map;
    }

    // ---- FeatureSelection
    static Set<String> base(int enc, Set<String> features) {
        Set<String> base = set();
        Map<Set<String>, Set<String>> map = classes(enc, features);
        Set<String> leftOut = set();
        for (Set<String> alpha : map.keySet()) {
            Set<String> eq = map.get(alpha);
            leftOut.clear();
            boolean has = false;
            for (String f : eq) {
                if (f.length() / enc == alpha.size()) { has = true; base.add(f); } else leftOut.add(f);
            }
            if (!has || leftOut.size() > 0) {
                Set<String> rep = !has ? repeats(enc, eq) : repeats(enc, leftOut);
                if (rep.size() > 0) base.addAll(base(enc, rep));
            }
        }
        return base;
    }

    static Set<String> repeats(int enc, Set<String> streams) {
        Set<String> rep = set(), acts = set();
        int index = 0;
        for (String s : streams) {
            int n = s.length() / enc;
            for (int i = 0; i < n; i++) acts.add(s.substring(i * enc, (i + 1) * enc));
            acts.add("Trace" + index);
            index++;
        }
        Enc e = new Enc(acts);
        index = 0;
        StringBuilder b = new StringBuilder();
        for (String s : streams) {
            int n = s.length() / enc;
            if (!ALLSTREAMS) b.setLength(0);
            for (int i = 0; i < n; i++) b.append(e.a2c.get(s.substring(i * enc, (i + 1) * enc)));
            b.append(e.a2c.get("Trace" + index));
            index++;
        }
        Tree t = new Tree(e.len, b.toString());
        Set<String> ext = t.maximal();
        ext.removeAll(t.superMaximal());
        for (String r : ext) {
            StringBuilder d = new StringBuilder();
            int n = r.length() / e.len;
            for (int j = 0; j < n; j++) d.append(e.c2a.get(r.substring(j * e.len, (j + 1) * e.len)));
            rep.add(d.toString());
        }
        return rep;
    }

    static int nFeatures, encLen, extLen;
    static int[][] idx, cnt; static long[] rowSum;

    /** Builds the sparse feature matrix behind ProM's distances. */
    static void build(List<String[][]> raw, int[] F) {
        // encodeLog
        Set<String> acts = set();
        for (String[][] t : raw) for (String[] ev : t) acts.add(ev[0] + "-" + ev[1]);
        Enc enc = new Enc(acts); encLen = enc.len;
        List<String> unique = new ArrayList<>();
        for (String[][] t : raw) {
            StringBuilder b = new StringBuilder();
            for (String[] ev : t) b.append(enc.a2c.get(ev[0] + "-" + ev[1]));
            unique.add(b.toString());
        }
        // computeFeatureSets: extended encoding with one symbol per trace of the log
        Set<String> ext = set();
        int ti = 0;
        for (int g = 0; g < raw.size(); g++) {
            for (int c = 0; c < F[g]; c++) {
                for (String[] ev : raw.get(g)) ext.add(ev[0] + "-" + ev[1]);
                ext.add("Trace" + ti); ti++;
            }
        }
        Enc xe = new Enc(ext); extLen = xe.len;
        Set<String> xs = set();
        for (String[][] t : raw) {
            StringBuilder b = new StringBuilder();
            for (String[] ev : t) b.append(xe.a2c.get(ev[0] + "-" + ev[1]));
            xs.add(b.toString());
        }
        StringBuilder combined = new StringBuilder();
        ti = 0;
        for (String s : xs) { combined.append(s).append(xe.a2c.get("Trace" + ti)); ti++; }
        Tree tree = new Tree(extLen, combined.toString());
        Map<Set<String>, Set<String>> byAlpha = classes(extLen, tree.maximal());
        // getOriginalEncodedAlphabetFeatureSetMap
        Set<String> union = set();
        for (Set<String> alpha : byAlpha.keySet()) {
            for (String r : byAlpha.get(alpha)) {
                StringBuilder d = new StringBuilder(); int n = r.length() / extLen;
                for (int i = 0; i < n; i++) d.append(enc.a2c.get(xe.c2a.get(r.substring(i * extLen, (i + 1) * extLen))));
                union.add(d.toString());
            }
        }
        Map<Set<String>, Set<String>> orig = classes(encLen, union);
        // FeatureSelection is built with the extended length, the features use the original one.
        int fs = TRUELEN ? encLen : extLen;
        Set<String> all = set();
        for (Set<String> a : orig.keySet()) all.addAll(orig.get(a));
        Set<String> baseSet = base(fs, all);
        Map<Set<String>, Set<String>> finalMap = classes(fs, baseSet);
        // Filter: alphabets of at most 10 elements
        List<Set<String>> feats = new ArrayList<>();
        for (Set<String> a : finalMap.keySet()) if (NOFILTER || a.size() <= 10) feats.add(finalMap.get(a));
        nFeatures = feats.size();
        idx = new int[unique.size()][]; cnt = new int[unique.size()][]; rowSum = new long[unique.size()];
        int[] tmp = new int[nFeatures], val = new int[nFeatures];
        for (int v = 0; v < unique.size(); v++) {
            String s = unique.get(v); int nz = 0;
            for (int j = 0; j < nFeatures; j++) {
                int c = 0;
                for (String f : feats.get(j)) {
                    if (f.isEmpty()) continue;
                    int p = s.indexOf(f);
                    while (p >= 0) { if (p % encLen == 0) c++; p = s.indexOf(f, p + 1); }
                }
                if (c != 0) { tmp[nz] = j; val[nz] = c; nz++; rowSum[v] += c; }
            }
            idx[v] = Arrays.copyOf(tmp, nz); cnt[v] = Arrays.copyOf(val, nz);
        }
        dense = new int[nFeatures];
    }
    static int[] dense;

    /** One row of EuclideanDistance: distances from a to every variant. */
    static float[] row(int a) {
        int n = idx.length; float[] out = new float[n];
        long sa = 0;
        for (int i = 0; i < idx[a].length; i++) { dense[idx[a][i]] = cnt[a][i]; sa += (long) cnt[a][i] * cnt[a][i]; }
        for (int c = 0; c < n; c++) {
            if (c == a) continue;
            long sum = sa;
            for (int i = 0; i < idx[c].length; i++) { long x = dense[idx[c][i]], y = cnt[c][i]; sum += (x - y) * (x - y) - x * x; }
            out[c] = (rowSum[a] != 0 || rowSum[c] != 0) ? (float) Math.sqrt((double) sum) : (float) Integer.MAX_VALUE;
        }
        for (int i = 0; i < idx[a].length; i++) dense[idx[a][i]] = 0;
        return out;
    }
}
