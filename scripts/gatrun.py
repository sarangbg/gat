#!/bin/env python
################################################################################
#
#   MRC FGU Computational Genomics Group
#
#   $Id: script_template.py 2871 2010-03-03 10:20:44Z andreas $
#
#   Copyright (C) 2009 Andreas Heger
#
#   This program is free software; you can redistribute it and/or
#   modify it under the terms of the GNU General Public License
#   as published by the Free Software Foundation; either version 2
#   of the License, or (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program; if not, write to the Free Software
#   Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.
#################################################################################
'''
gat-run - run the genomic annotation tool
=============================================

:Author: Andreas Heger
:Release: $Id$
:Date: |today|
:Tags: Python

Purpose
-------

This script compares one or more genomic segments of interest 
against one more other genomic annotations.

Usage
-----

Example::

   python gatrun.py 
      --segment-file=segments.bed.gz 
      --workspace-file=workspace.bed.gz 
      --annotation-file=annotations_architecture.bed.gz  
 
Type::

   python gat-run.py --help

for command line help.

Documentation
-------------

Code
----

'''

import os, sys, re, optparse, collections, types, glob, time
import numpy

import Experiment as E
import IOTools
import gat

try:
    import matplotlib.pyplot as plt
    HASPLOT = True
except (ImportError,RuntimeError):
    HASPLOT = False

def fromSegments( options, args ):
    '''run analysis from segment files. 

    This is the most common use case.
    '''

    tstart = time.time()

    def expandGlobs( infiles ):
        return IOTools.flatten( [ glob.glob( x ) for x in infiles ] )
        
    options.segment_files = expandGlobs( options.segment_files )
    options.annotation_files = expandGlobs( options.annotation_files )
    options.workspace_files = expandGlobs( options.workspace_files )
    options.sample_files = expandGlobs( options.sample_files )

    ##################################################
    # arguments sanity check
    if not options.segment_files:
        raise ValueError("please specify at least one segment file" )
    if not options.annotation_files:
        raise ValueError("please specify at least one annotation file" )
    if not options.workspace_files:
        raise ValueError("please specify at least one workspace file" )

    ##################################################
    ##################################################
    ##################################################
    # process input
    def dumpStats( coll, section ):
        if section in options.output_stats or \
                "all" in options.output_stats or \
                len( [ x for x in options.output_stats if re.search( x, section ) ] ) > 0:
            coll.outputStats( E.openOutputFile( section ) )

    def readSegmentList( label, filenames ):
        # read one or more segment files
        results = gat.IntervalCollection( name = label )
        E.info( "%s: reading tracks from %i files" % (label, len(filenames)))
        results.load( filenames )
        E.info( "%s: read %i tracks from %i files" % (label, len(results), len(filenames)))
        dumpStats( results, "stats_%s_raw" % label )
        results.normalize()
        dumpStats( results, "stats_%s_normed" % label )
        return results

    # read one or more segment files
    segments = readSegmentList( "segments", options.segment_files)
    annotations = readSegmentList( "annotations", options.annotation_files)
    workspaces = readSegmentList( "workspaces", options.workspace_files)

    # intersect workspaces to build a single workspace
    E.info( "collapsing workspaces" )
    workspaces.collapse()
    dumpStats( workspaces, "stats_workspaces_collapsed" )

    # use merged workspace only, discard others
    workspaces.restrict("collapsed")

    # build isochores or intersect annotations/segments with workspace
    if options.isochore_files:

        # read one or more isochore files
        isochores = gat.IntervalCollection( name = "isochores" )
        E.info( "%s: reading isochores from %i files" % ("isochores", len(options.isochore_files)))
        isochores.load( options.isochore_files )
        dumpStats( isochores, "stats_isochores_raw" )

        # merge isochores and check if consistent (fully normalized)
        isochores.sort()

        # check that there are no overlapping segments within isochores
        isochores.check()

        # TODO: flag is_normalized not properly set
        isochores.normalize()

        # check that there are no overlapping segments between isochores

        # intersect isochores and workspaces, segments and annotations
        E.info( "adding isochores to workspace" )
        workspaces.toIsochores( isochores )
        annotations.toIsochores( isochores )
        segments.toIsochores( isochores )
        
        if workspaces.sum() == 0:
            raise ValueError( "isochores and workspaces do not overlap" )
        if annotations.sum() == 0:
            raise ValueError( "isochores and annotations do not overlap" )
        if segments.sum() == 0:
            raise ValueError( "isochores and segments do not overlap" )

        dumpStats( workspaces, "stats_workspaces_isochores" )
        dumpStats( annotations, "stats_annotations_isochores" )
        dumpStats( segments, "stats_segments_isochores" )
    
    else:
        # intersect workspace and segments/annotations
        annotations.filter( workspaces["collapsed"] )
        segments.filter( workspaces["collapsed"] )

        dumpStats( annotations, "stats_annotations_pruned" )
        dumpStats( segments, "stats_segments_pruned" )

    workspace = workspaces["collapsed"] 

    # segments.dump( open("segments_dump.bed", "w" ) )
    # workspaces.dump( open("workspaces_dump.bed", "w" ) )

    E.info( "intervals loaded in %i seconds" % (time.time() - tstart) )

    # output overlap stats
    # output segment densities per workspace
    for track in segments.tracks:
        workspaces.outputOverlapStats( E.openOutputFile( "overlap_%s" % track), 
                                       segments[track] )

    ##################################################
    ##################################################
    ##################################################
    ## check memory requirements
    counts = segments.countsPerTrack() 
    max_counts = max(counts.values())
    # previous algorithm: memory requirements if all samples are stored
    memory = 8 * 2 * options.num_samples * max_counts * len(workspace)

    ##################################################
    ##################################################
    ##################################################
    # initialize sampler
    sampler = gat.SamplerAnnotator(
        bucket_size = options.bucket_size,
        nbuckets = options.nbuckets )

    ##################################################
    ##################################################
    ##################################################
    # initialize counter
    if options.counter == "nucleotide-overlap":
        counter = gat.CounterNucleotideOverlap()
    elif options.counter == "nucleotide-density":
        counter = gat.CounterNucleotideDensity()
    elif options.counter == "segment-overlap":
        counter = gat.CounterSegmentOverlap()
    else:
        raise ValueError("unknown counter '%s'" % options.counter )

    ##################################################
    ##################################################
    ##################################################
    ## compute
    ##################################################
    annotator_results = gat.run( segments, 
                                 annotations, 
                                 workspace,
                                 sampler, 
                                 counter,
                                 num_samples = options.num_samples,
                                 cache = options.cache,
                                 output_counts = options.output_filename_counts,
                                 output_samples_pattern = options.output_samples_pattern,
                                 sample_files = options.sample_files )

    return annotator_results

class DummyAnnotatorResult:

    format_observed = "%i"
    format_expected = "%6.4f"
    format_fold = "%6.4f"
    format_pvalue = "%6.4e"

    def __init__( self ):
        pass

    @classmethod
    def _fromLine( cls, line ):
        x = cls()
        data = line[:-1].split("\t")
        x.track, x.annotation = data[:2]
        x.observed, x.expected, x.lower95, x.upper95, x.stddev, x.fold, x.pvalue, x.qvalue = \
            map(float, data[2:] )
        
        return x

    def __str__(self):
        return "\t".join( (self.track,
                           self.annotation,
                           self.format_observed % self.observed,
                           self.format_expected % self.expected,
                           self.format_expected % self.lower95,
                           self.format_expected % self.upper95,
                           self.format_expected % self.stddev,
                           self.format_fold % self.fold,
                           self.format_pvalue % self.pvalue,
                           self.format_pvalue % self.qvalue ) )

def fromResults( filename ):
    '''load annotator results from a tab-separated results table.'''

    annotator_results = collections.defaultdict( dict )

    with open(filename, "r") as infile:
        for line in infile:
            if line.startswith("#"): continue
            if line.startswith("track"): continue
            r = DummyAnnotatorResult._fromLine( line ) 
            annotator_results[r.track][r.annotation] = r
            
    return annotator_results

def main( argv = None ):
    """script main.

    parses command line options in sys.argv, unless *argv* is given.
    """

    if not argv: argv = sys.argv

    # setup command line parser
    parser = optparse.OptionParser( version = "%prog version: $Id: script_template.py 2871 2010-03-03 10:20:44Z andreas $", 
                                    usage = globals()["__doc__"] )

    parser.add_option("-a", "--annotation-file", "--annotations", dest="annotation_files", type="string", action="append",
                      help="filename with annotations [default=%default]."  )

    parser.add_option("-s", "--segment-file", "--segments", dest="segment_files", type="string", action="append",
                      help="filename with segments. Also accepts a glob in parentheses [default=%default]."  )

    parser.add_option("-w", "--workspace-file", "--workspace", dest="workspace_files", type="string", action="append",
                      help="filename with workspace segments. Also accepts a glob in parentheses [default=%default]."  )

    parser.add_option("-i", "--isochore-file", "--isochores", dest="isochore_files", type="string", action="append",
                      help="filename with isochore segments. Also accepts a glob in parentheses [default=%default]."  )

    parser.add_option("-l", "--sample-file", dest="sample_files", type="string", action="append",
                      help="filename with sample files. Start processing from samples [default=%default]."  )

    parser.add_option("-c", "--counter", dest="counter", type="choice",
                      choices=("nucleotide-overlap", 
                               "nucleotide-density",
                               "segment-overlap", ),
                      help="quantity to test [default=%default]."  )

    parser.add_option("-n", "--num-samples", dest="num_samples", type="int", 
                      help="number of samples to compute [default=%default]."  )

    parser.add_option("-e", "--cache", dest="cache", type="string", 
                      help="filename for caching samples [default=%default]."  )

    parser.add_option("-o", "--order", dest="output_order", type="choice",
                      choices = ( "track", "annotation", "fold", "pvalue", "qvalue" ),
                      help="order results in output by fold, track, etc. [default=%default]."  )

    parser.add_option("-p", "--pvalue-method", dest="pvalue_method", type="choice",
                      choices = ( "empirical", "norm", ),
                      help="type of pvalue reported [default=%default]."  )

    parser.add_option("-q", "--qvalue-method", dest="qvalue_method", type="choice",
                      choices = ( "storey", ),
                      help="method to perform multiple testing correction by controlling the fdr [default=%default]."  )

    parser.add_option( "--qvalue-lambda", dest="qvalue_lambda", type="float",
                      help="fdr computation: lambda [default=%default]."  )

    parser.add_option( "--qvalue-pi0-method", dest="qvalue_pi0_method", type="choice",
                       choices = ("smoother", "bootstrap" ),
                       help="fdr computation: method for estimating pi0 [default=%default]."  )

    parser.add_option( "--counts-file", dest="input_filename_counts", type="string", 
                      help="start processing from counts - no segments required [default=%default]."  )

    parser.add_option( "--output-counts-file", dest="output_filename_counts", type="string", 
                      help="output counts to filename [default=%default]."  )

    parser.add_option( "--results-file", dest="input_filename_results", type="string", 
                      help="start processing from results - no segments required [default=%default]."  )

    parser.add_option( "--output-plots-pattern", dest="output_plots_pattern", type="string", 
                       help="output pattern for plots [default=%default]" )

    parser.add_option( "--output-samples-pattern", dest="output_samples_pattern", type="string", 
                       help="output pattern for samples. Samples are stored in bed format, one for "
                            " each segment [default=%default]" )

    parser.add_option( "--bucket-size", dest="bucket_size", type="int", 
                       help="size of a bin for histogram of segment lengths [default=%default]" )

    parser.add_option( "--nbuckets", dest="nbuckets", type="int", 
                       help="number of bins for histogram of segment lengths [default=%default]" )

    parser.add_option( "--output-stats", dest="output_stats", type="choice",
                      choices = ( "all", 
                                  "annotations", "segments", 
                                  "workspaces", "isochores",
                                  "overlap" ),
                      help="type of pvalue reported [default=%default]."  )

    parser.set_defaults(
        annotation_files = [],
        segment_files = [],
        workspace_files = [],  
        sample_files = [],
        num_samples = 1000,
        nbuckets = 100000,
        bucket_size = 1,
        counter = "nucleotide-overlap",
        output_stats = [],
        output_filename_counts = None,
        output_order = "fold",
        cache = None,
        input_filename_counts = None,
        input_filename_results = None,
        pvalue_method = "empirical",
        output_plots_pattern = None,
        output_samples_pattern = None,
        qvalue_method = "storey",
        qvalue_lambda = None,
        qvalue_pi0_method = "smoother",
        )

    ## add common options (-h/--help, ...) and parse command line 
    (options, args) = E.Start( parser, argv = argv, add_output_options = True )

    ##################################################
    if options.input_filename_counts:
        annotator_results = gat.fromCounts( options.input_filename_counts )
    elif options.input_filename_results:
        E.info( "reading annotator results from %s" % options.input_filename_results )
        annotator_results = fromResults( options.input_filename_results )
    else:
        annotator_results = fromSegments( options, args )

    if options.pvalue_method != "empirical":
        E.info("updating pvalues to %s" % options.pvalue_method )
        gat.updatePValues( gat.iterator_results(annotator_results), options.pvalue_method )

    ##################################################
    ##################################################
    ##################################################
    ## compute global fdr
    ##################################################
    E.info( "computing FDR statistics" )
    gat.updateQValues( list(gat.iterator_results(annotator_results)), 
                       method = options.qvalue_method,
                       vlambda = options.qvalue_lambda,
                       pi0_method = options.qvalue_pi0_method )
    
    ##################################################
    # plot histograms
    if options.output_plots_pattern and HASPLOT:

        def buildPlotFilename( options, key ):
            filename = re.sub("%s", key, options.output_plots_pattern)
            filename = re.sub("[^a-zA-Z0-9-_./]", "_", filename )
            dirname = os.path.dirname( filename )
            if dirname and not os.path.exists( dirname ): os.makedirs( dirname )
            return filename

        E.info("plotting sample stats" )

        for r in gat.iterator_results(annotator_results):
            plt.figure()
            key = "%s-%s" % (r.track, r.annotation)
            s = r.samples
            hist, bins = numpy.histogram( s,
                                          normed = True,
                                          bins = 100 )
            # bins = numpy.arange( s.min(), s.max() + 1, 1.0) )
            plt.bar( bins[:-1], hist, width=1.0, label = key )
            sigma = r.stddev
            mu = r.expected
            plt.plot(bins, 
                     1.0/(sigma * numpy.sqrt(2 * numpy.pi)) *
                     numpy.exp( - (bins - mu)**2 / (2 * sigma**2) ),
                     label = "fit",
                     linewidth=2, 
                     color='r' )

            plt.legend()
            filename = buildPlotFilename( options, key )
            plt.savefig( filename )

        E.info( "plotting P-value distribution" )
        
        key = "pvalue"
        plt.figure()

        x,bins,y = plt.hist( [r.pvalue for r in gat.iterator_results(annotator_results) ],
                             bins = numpy.arange( 0, 1.05, 0.025) ,
                             label = "pvalue" )

        plt.hist( [r.qvalue for r in gat.iterator_results(annotator_results) ],
                  bins = numpy.arange( 0, 1.05, 0.025) ,
                  label = "qvalue",
                  alpha=0.5 )

        plt.legend()

        # hist, bins = numpy.histogram( \
        #     [r.pvalue for r in gat.iterator_results(annotator_results) ],
        #     bins = 20 )
        # plt.plot( bins[:-1], hist, label = key )

        filename = buildPlotFilename( options, key )
        plt.savefig( filename )

    ##################################################
    ##################################################
    ## output
    ##################################################
    outfile = options.stdout

    outfile.write("\t".join( gat.AnnotatorResult.headers ) + "\n" )

    output = list( gat.iterator_results( annotator_results ) )
    if options.output_order == "track":
        output.sort( key = lambda x: (x.track, x.annotation) )
    elif options.output_order == "annotation":
        output.sort( key = lambda x: (x.annotation, x.track) )
    elif options.output_order == "fold":
        output.sort( key = lambda x: x.fold )
    elif options.output_order == "pvalue":
        output.sort( key = lambda x: x.pvalue )
    elif options.output_order == "qvalue":
        output.sort( key = lambda x: x.qvalue )
    else:
        raise ValueError("unknown sort order %s" % options.output_order )

    for result in output:
        outfile.write( str(result) + "\n" )
            
    ## write footer and output benchmark information.
    E.Stop()

if __name__ == "__main__":
    sys.exit( main( sys.argv) )
