import json
import os
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import pandas as pd
from Bio import SeqIO

from src.models import logs
from src.utils import files, seq, docker, cmds, operations


def parse_filenames(path, ext=".fna"):
    return [name for name in os.listdir(path) if name.endswith(ext)]


def format_contigs(filenames, input_dir, working_dir):
    namemap = {}
    for i, oldname in enumerate(filenames, 1):
        newname = "Genome_{}.fa".format(i)
        namemap[oldname] = newname
        with open(files.joinpath(working_dir, newname), "w") as file:
            for j, contig in enumerate(SeqIO.parse(files.joinpath(input_dir, oldname), "fasta"), 1):
                seqid = "G_{}::C_{}".format(i, j)
                SeqIO.write(seq.replace_id(contig, seqid), file, "fasta")
    return namemap


def move_file(annotate_dir, dest_dir, ext):
    for folder in os.listdir(annotate_dir):
        path = files.joinpath(annotate_dir, folder)
        for file in os.listdir(path):
            current_file = files.joinpath(path, file)
            if file.endswith(ext):
                os.rename(current_file, files.joinpath(dest_dir, file))


def create_noncds(database_dir, gff_dir):
    noncds = defaultdict(list)
    for file in os.listdir(gff_dir):
        name, ext = file.split(".")
        for line in open(files.joinpath(gff_dir, file), "r").read().splitlines():
            if line.startswith("##sequence") or line.startswith("##gff"):
                continue
            if line.startswith("##FASTA"):
                break

            token = line.split("\t")
            seq_type, annotation = token[2], token[8]

            if annotation.startswith("ID="):
                prokkaid = annotation.split(";")[0][3:]
                if seq_type != "CDS":
                    noncds[name].append(prokkaid)
    with open(files.joinpath(database_dir, "nonCDS.json"), "w") as file:
        file.write(json.dumps(noncds))


def extract_profiles(roary_matrix_file, metadata_file, metadata_cols=13):
    matrix = pd.read_csv(roary_matrix_file)
    matrix["Gene"] = matrix["Gene"].str.replace("/", "_")
    rename_cols = {"Gene": "locus_id", "No. isolates": "num_isolates", "No. sequences": "num_sequences",
                   "Annotation": "description"}
    matrix.rename(columns=rename_cols, inplace=True)
    matrix.set_index("locus_id", inplace=True)
    save_locus_metadata(matrix, metadata_file)
    profiles = matrix.iloc[:, metadata_cols:]
    isolates = len(matrix.columns) - metadata_cols
    return profiles, isolates


def save_locus_metadata(matrix, metadata_file, select_col=None, repeat_tol=1.5):
    if not select_col:
        select_col = ["num_isolates", "num_sequences", "description", "is_paralogs"]
    avg = "Avg sequences per isolate"
    matrix["is_paralogs"] = [x > repeat_tol for x in matrix[avg]]
    matrix[select_col].to_csv(metadata_file, sep="\t")


def collect_allele_infos(profiles, ffn_dir):
    freq = defaultdict(Counter)
    new_profiles = []
    for subject, profile in profiles.iteritems():
        ffn_file = files.joinpath(ffn_dir, "{}.ffn".format(subject))
        seqs = {record.id: record.seq for record in SeqIO.parse(ffn_file, "fasta")}

        new_profile = pd.Series(name=subject)
        for locus, prokka_str in profile.dropna().iteritems():
            if "\t" not in prokka_str:
                allele = seqs[prokka_str]
                freq[locus].update([allele])
                new_profile.set_value(locus, operations.make_seqid(allele))
            else:
                prokka_id = prokka_str.split("\t")
                alleles = [seqs[x] for x in prokka_id]
                freq[locus].update(alleles)
                v = "\t".join(operations.make_seqid(x) for x in alleles)
                new_profile.set_value(locus, v)
        new_profiles.append(new_profile)
    new_profiles = pd.concat(new_profiles, axis=1).sort_index().sort_index(axis=1)
    return new_profiles, freq


def save_sequences(freq, seq_file):
    with open(seq_file, "w") as file:
        file.write("locus_id\tallele_id\tdna_seq\tpeptide_seq\tcount")
        for locus, counter in freq.items():
            for allele, count in counter.items():
                dna_seq = str(allele)
                pept_seq = str(allele.translate(table=11))
                allele_id = operations.make_seqid(dna_seq)
                file.write("\n{}\t{}\t{}\t{}\t{}".format(locus, allele_id, dna_seq, pept_seq, count))


def make_schemes(locusmeta_file, scheme_file, freq, total_isolates):
    refseqs = {locus: operations.make_seqid(counter.most_common(1)[0][0]) for locus, counter in freq.items()}
    schemes = pd.read_csv(locusmeta_file, sep="\t")
    schemes["occurrence"] = list(map(lambda x: round(x/total_isolates * 100, 2), schemes["num_isolates"]))
    schemes["ref_allele"] = list(map(lambda x: refseqs[x], schemes["locus_id"]))
    schemes = schemes.loc[schemes["occurrence"] >= 2.0, ["locus_id", "occurrence", "ref_allele"]]
    schemes.to_csv(scheme_file, index=False, sep="\t")


def annotate_configs(input_dir, output_dir, logger=None, threads=8, use_docker=True):
    if not logger:
        logger = logs.console_logger(__name__)

    logger.info("Formating contigs...")
    filenames = parse_filenames(input_dir)

    genome_dir = files.joinpath(output_dir, "Genomes")
    files.create_if_not_exist(genome_dir)
    namemap = format_contigs(filenames, input_dir, genome_dir)
    with open(files.joinpath(output_dir, "namemap.json"), "w") as f:
        f.write(json.dumps(namemap))

    logger.info("Annotating...")
    annotate_dir = files.joinpath(output_dir, "Annotated")
    files.create_if_not_exist(annotate_dir)
    if use_docker:
        docker.prokka(genome_dir, annotate_dir)
    else:
        c = [cmds.form_prokka_cmd(x, genome_dir, annotate_dir) for x in namemap.values()]
        with ProcessPoolExecutor(int(threads / 2)) as executor:
            executor.map(os.system, c)

    logger.info("Moving protein CDS (.ffn) files...")
    ffn_dir = files.joinpath(output_dir, "FFN")
    files.create_if_not_exist(ffn_dir)
    move_file(annotate_dir, ffn_dir, ".ffn")

    logger.info("Moving annotation (.gff) files...")
    gff_dir = files.joinpath(output_dir, "GFF")
    files.create_if_not_exist(gff_dir)
    move_file(annotate_dir, gff_dir, ".gff")

    logger.info("Creating nonCDS.json...")
    create_noncds(output_dir, gff_dir)


def make_database(output_dir, logger=None, threads=2, use_docker=True):
    if not logger:
        logger = logs.console_logger(__name__)

    database_dir = files.joinpath(output_dir, "database")
    files.create_if_not_exist(database_dir)

    logger.info("Calculating the pan genome...")
    min_identity = 95
    if use_docker:
        docker.roary(files.joinpath(output_dir, "GFF"), output_dir, min_identity, threads)
    else:
        c = cmds.form_roary_cmd(files.joinpath(output_dir, "GFF"), output_dir, min_identity, threads)
        os.system(c)

    logger.info("Extract profiles from roary result matrix...")
    matrix_file = files.joinpath(output_dir, "roary", "gene_presence_absence.csv")
    locusmeta_file = files.joinpath(database_dir, "locus_meta.tsv")
    profiles, total_isolates = extract_profiles(matrix_file, locusmeta_file)

    logger.info("Collecting allele profiles and making allele frequencies and reference sequence...")
    ffn_dir = files.joinpath(output_dir, "FFN")
    profile_file = files.joinpath(database_dir, "allele_profiles.tsv")
    profiles, freq = collect_allele_infos(profiles, ffn_dir)
    profiles.to_csv(profile_file, sep="\t")

    sequences_file = files.joinpath(database_dir, "alleles.tsv")
    save_sequences(freq, sequences_file)

    logger.info("Making dynamic schemes...")
    scheme_file = files.joinpath(database_dir, "scheme.tsv")
    make_schemes(locusmeta_file, scheme_file, freq, total_isolates)
    logger.info("Done!!")

